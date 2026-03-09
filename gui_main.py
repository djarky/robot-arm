import sys
import cv2
import numpy as np
import serial.tools.list_ports
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QDockWidget, 
                             QFormLayout, QDoubleSpinBox, QComboBox, QGroupBox, QSlider,
                             QListWidget, QListWidgetItem, QInputDialog, QFrame, QScrollArea,
                             QSizePolicy)
from PySide6.QtCore import QTimer, Qt, QThread, Signal, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon

class PoseWidget(QFrame):
    def __init__(self, pose_name, thumb_path, parent=None, show_delete=True):
        super().__init__(parent)
        self.pose_name = pose_name
        self.setFixedSize(85, 110) # Reducido aún más para asegurar 2 columnas
        self.setStyleSheet("QFrame { background-color: #333; border-radius: 5px; border: 1px solid #555; } QFrame:hover { border: 1px solid #2196F3; }")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        if show_delete:
            self.btn_del = QPushButton("×")
            self.btn_del.setFixedSize(18, 18)
            self.btn_del.setStyleSheet("background-color: #c62828; color: white; border-radius: 9px; font-weight: bold; font-size: 14px;")
            layout.addWidget(self.btn_del, 0, Qt.AlignRight)
        else:
            layout.addSpacing(18) # Space where delete button would be
        
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(90, 60)
        if os.path.exists(thumb_path):
            pix = QPixmap(thumb_path).scaled(90, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pix)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("border: none; background: transparent;")
        
        self.name_label = QLabel(pose_name)
        self.name_label.setStyleSheet("color: white; font-size: 10px; font-weight: bold; border: none;")
        self.name_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.icon_label, 0, Qt.AlignCenter)
        layout.addWidget(self.name_label, 0, Qt.AlignCenter)
        layout.addStretch()

class TimeConnectorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(60)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.time_input = QDoubleSpinBox()
        self.time_input.setRange(0.1, 10.0)
        self.time_input.setValue(2.0)
        self.time_input.setSuffix("s")
        self.time_input.setStyleSheet("font-size: 10px;")
        
        arrow = QLabel("→")
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet("font-size: 20px; color: #888;")
        
        layout.addStretch()
        layout.addWidget(self.time_input)
        layout.addWidget(arrow)
        layout.addStretch()
import mediapipe as mp
import subprocess
import json
import socket
import serial
import serial.tools.list_ports

class CameraThread(QThread):
    image_update = Signal(np.ndarray, list, list) # frame, pose_lms, hand_lms

    def __init__(self):
        super().__init__()
        self.running = True
        self.pose_model = 'pose_landmarker.task'
        self.hand_model = 'hand_landmarker.task'

    def run(self):
        import mediapipe as mp
        BaseOptions = mp.tasks.BaseOptions
        
        # Pose Options
        PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
        
        # Hand Options
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        
        VisionRunningMode = mp.tasks.vision.RunningMode

        pose_options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.pose_model),
            running_mode=VisionRunningMode.IMAGE
        )
        hand_options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.hand_model),
            running_mode=VisionRunningMode.IMAGE,
            num_hands=1
        )
        
        cap = cv2.VideoCapture(0)
        with PoseLandmarker.create_from_options(pose_options) as pose_landmarker, \
             HandLandmarker.create_from_options(hand_options) as hand_landmarker:
             
            while self.running:
                success, frame = cap.read()
                if success:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    
                    pose_result = pose_landmarker.detect(mp_image)
                    hand_result = hand_landmarker.detect(mp_image)
                    
                    pose_lms = pose_result.pose_landmarks if pose_result.pose_landmarks else []
                    hand_lms = hand_result.hand_landmarks if hand_result.hand_landmarks else []
                    
                    self.image_update.emit(frame, pose_lms, hand_lms)
                else:
                    self.msleep(30)
        cap.release()

    def stop(self):
        self.running = False
        self.wait()

class RobotGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Robot Arm Control System")
        self.resize(1200, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Socket para enviar a la simulación
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_addr = ("127.0.0.1", 5005)

        # Socket para recibir de la simulación
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.recv_sock.bind(("127.0.0.1", 5006))
            self.recv_sock.setblocking(False)
        except Exception as e:
            print(f"No se pudo enlazar el puerto de feedback: {e}")

        # Timer para feedback UDP
        self.feedback_timer = QTimer()
        self.feedback_timer.timeout.connect(self.sync_from_sim)
        self.feedback_timer.start(50) # Polling cada 50ms

        # Subprocess management
        self.ser = None
        self.sim_proc = None

        # Left Panel: 3D Simulation Control
        self.sim_panel = QGroupBox("3D Simulation View")
        sim_layout = QVBoxLayout()
        
        # Top Spawn Panel (New Location)
        self.setup_sim_top_panel(sim_layout)
        
        self.sim_container = QWidget()
        self.sim_container.setStyleSheet("background-color: black;")
        self.sim_container.setMinimumSize(600, 400)
        
        button_layout = QHBoxLayout()
        self.btn_launch_sim = QPushButton("Lanzar Simulación 3D (Ursina)")
        self.btn_launch_sim.clicked.connect(self.launch_simulation)
        self.btn_reset_cam = QPushButton("Reset View")
        self.btn_reset_cam.clicked.connect(self.reset_camera_sim)
        button_layout.addWidget(self.btn_launch_sim)
        button_layout.addWidget(self.btn_reset_cam)
        
        sim_layout.addWidget(self.sim_container)
        
        # Bottom Timeline Panel (Visual Quadricula)
        self.setup_visual_timeline(sim_layout)
        
        button_layout = QHBoxLayout()
        self.btn_launch_sim = QPushButton("Lanzar Simulación 3D (Ursina)")
        self.btn_launch_sim.clicked.connect(self.launch_simulation)
        self.btn_reset_cam = QPushButton("Reset View")
        self.btn_reset_cam.clicked.connect(self.reset_camera_sim)
        self.btn_play_seq = QPushButton("▶ REPRODUCIR SECUENCIA")
        self.btn_play_seq.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        self.btn_play_seq.clicked.connect(self.play_sequence)
        
        button_layout.addWidget(self.btn_launch_sim)
        button_layout.addWidget(self.btn_reset_cam)
        button_layout.addWidget(self.btn_play_seq)
        
        sim_layout.addLayout(button_layout)
        sim_layout.setStretch(0, 0) # Top Panel
        sim_layout.setStretch(1, 10) # Sim Container
        sim_layout.setStretch(2, 0) # Timeline Panel
        sim_layout.setStretch(3, 0) # Button Layout
        
        self.sim_panel.setLayout(sim_layout)
        self.main_layout.addWidget(self.sim_panel, 7) # Ajustado para mayor compatibilidad de grid

        # Right Panel: Camera and Controls (con Scroll Area)
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(5, 5, 5, 5)
        self.right_scroll.setWidget(self.right_panel)
        
        self.main_layout.addWidget(self.right_scroll, 3) # Panel derecho con 30% de ancho

        self.setup_camera_panel()
        self.setup_control_panel()
        
        # Initialize ports
        self.refresh_ports()
        
        # Load last session config
        self.load_config()

        # Camera Thread
        self.cam_thread = CameraThread()
        self.cam_thread.image_update.connect(self.update_image)
        self.camera_active = False

        # Pose & Movement Data
        self.poses_file = "poses.json"
        self.saved_poses = {} # { "Pose Name": [a,b,c] }
        self.pose_icons_dir = "pose_thumbnails"
        if not os.path.exists(self.pose_icons_dir):
            os.makedirs(self.pose_icons_dir)
        self.load_poses_data()

        # Interpolation Engine
        self.interp_timer = QTimer()
        self.interp_timer.timeout.connect(self.update_interpolation)
        self.target_angles = [0, 0, 0]
        self.current_interp_sequence = []
        self.current_seq_index = -1
        self.interp_steps = 0
        self.interp_count = 0
        self.interp_deltas = [0, 0, 0]

    def setup_sim_top_panel(self, parent_layout):
        spawn_row = QHBoxLayout()
        spawn_row.addWidget(QLabel("Spawn:"))
        self.obj_type = QComboBox()
        self.obj_type.addItems(["cube", "cylinder"])
        self.obj_size = QDoubleSpinBox(); self.obj_size.setValue(0.5); self.obj_size.setSingleStep(0.1)
        self.obj_mass = QDoubleSpinBox(); self.obj_mass.setValue(1.0)
        self.btn_spawn = QPushButton("Spawn")
        self.btn_spawn.clicked.connect(self.spawn_request)
        
        spawn_row.addWidget(self.obj_type)
        spawn_row.addWidget(QLabel("S:"))
        spawn_row.addWidget(self.obj_size)
        spawn_row.addWidget(QLabel("M:"))
        spawn_row.addWidget(self.obj_mass)
        spawn_row.addWidget(self.btn_spawn)
        spawn_row.addStretch()
        parent_layout.addLayout(spawn_row)

    def setup_visual_timeline(self, parent_layout):
        self.timeline_group = QGroupBox("Timeline de Movimiento")
        tl_main_vbox = QVBoxLayout()
        tl_main_vbox.setContentsMargins(5, 2, 5, 5)
        tl_main_vbox.setSpacing(0)
        
        # Header con botone de colapsar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_toggle_tl = QPushButton("▼") # Flecha hacia abajo (abierto)
        self.btn_toggle_tl.setFixedSize(30, 20)
        self.btn_toggle_tl.clicked.connect(self.toggle_timeline)
        header_layout.addWidget(self.btn_toggle_tl)
        header_layout.addStretch()
        
        # Contenedor de TODO el contenido del timeline (el que se oculta)
        self.tl_container_widget = QWidget()
        self.tl_container_layout = QHBoxLayout(self.tl_container_widget)
        self.tl_container_layout.setContentsMargins(0, 2, 0, 0)
        
        # Scroll Area para el timeline horizontal
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidgetResizable(True)
        self.tl_scroll.setFixedHeight(150)
        self.tl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        
        self.tl_content = QWidget()
        self.tl_layout = QHBoxLayout(self.tl_content)
        self.tl_layout.setAlignment(Qt.AlignLeft)
        self.tl_scroll.setWidget(self.tl_content)
        
        # Botones de control lateral
        self.tl_side_controls = QWidget()
        side_ctrl_layout = QVBoxLayout(self.tl_side_controls)
        side_ctrl_layout.setContentsMargins(5, 0, 0, 0)
        
        self.btn_add_tl = QPushButton("+")
        self.btn_add_tl.setFixedSize(40, 40)
        self.btn_add_tl.setStyleSheet("font-size: 24px; font-weight: bold; background-color: #2196F3; color: white; border-radius: 20px;")
        self.btn_add_tl.clicked.connect(self.add_selected_to_timeline)
        
        self.btn_clear_tl = QPushButton("Clear")
        self.btn_clear_tl.setFixedWidth(50)
        self.btn_clear_tl.clicked.connect(self.clear_visual_timeline)
        
        side_ctrl_layout.addWidget(self.btn_add_tl)
        side_ctrl_layout.addWidget(self.btn_clear_tl)
        
        self.tl_container_layout.addWidget(self.tl_scroll)
        self.tl_container_layout.addWidget(self.tl_side_controls)
        
        tl_main_vbox.addLayout(header_layout)
        tl_main_vbox.addWidget(self.tl_container_widget)
        
        self.timeline_group.setLayout(tl_main_vbox)
        self.timeline_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        parent_layout.addWidget(self.timeline_group)
        self.timeline_widgets = []

    def toggle_timeline(self):
        is_visible = self.tl_container_widget.isVisible()
        self.tl_container_widget.setVisible(not is_visible)
        self.btn_toggle_tl.setText("▲" if is_visible else "▼")
        
        if is_visible:
            # Colapsado
            self.timeline_group.setMaximumHeight(50)
        else:
            # Expandido
            self.timeline_group.setMaximumHeight(250)
            
        # Forzar al layout a auto-acomodarse
        self.main_layout.activate()

    def setup_camera_panel(self):
        group = QGroupBox("Camera Tracking")
        layout = QVBoxLayout()
        self.cam_label = QLabel("Cámara desactivada")
        self.cam_label.setAlignment(Qt.AlignCenter)
        self.cam_label.setFixedSize(200, 150) # Más pequeño
        self.cam_label.setStyleSheet("background-color: black; color: white; border-radius: 5px;")
        
        self.btn_toggle_cam = QPushButton("Activar Seguimiento")
        self.btn_toggle_cam.clicked.connect(self.toggle_camera)
        
        layout.addWidget(self.cam_label)
        layout.addWidget(self.btn_toggle_cam)
        group.setLayout(layout)
        self.right_layout.addWidget(group)

    def setup_control_panel(self):
        # Joint Sliders (Manual Control)
        joint_group = QGroupBox("Manual Control")
        joint_layout = QFormLayout()
        self.sliders = []
        for i in range(3):
            s = QSlider(Qt.Horizontal)
            s.setRange(-180, 180)
            s.setValue(0)
            s.valueChanged.connect(self.send_angles)
            joint_layout.addRow(f"J{i}:", s)
            self.sliders.append(s)
        joint_group.setLayout(joint_layout)
        self.right_layout.addWidget(joint_group)

        # Pose Gallery (Custom List)
        pose_group = QGroupBox("Galería de Poses")
        pose_layout = QVBoxLayout()
        
        self.pose_list = QListWidget()
        self.pose_list.setViewMode(QListWidget.IconMode)
        self.pose_list.setResizeMode(QListWidget.Adjust)
        self.pose_list.setWrapping(True)
        self.pose_list.setGridSize(QSize(90, 115))
        self.pose_list.setSpacing(2)
        self.pose_list.setMinimumHeight(225)
        self.pose_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.pose_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pose_list.itemDoubleClicked.connect(self.load_pose_item)
        self.pose_list.setSelectionMode(QListWidget.SingleSelection)
        
        btns = QHBoxLayout()
        self.btn_save_pose = QPushButton("Snapshot")
        self.btn_save_pose.clicked.connect(self.save_current_pose)
        self.btn_del_pose = QPushButton("Del")
        self.btn_del_pose.clicked.connect(self.delete_selected_pose)
        btns.addWidget(self.btn_save_pose)
        btns.addWidget(self.btn_del_pose)
        
        pose_layout.addWidget(self.pose_list)
        pose_layout.addLayout(btns)
        pose_group.setLayout(pose_layout)
        self.right_layout.addWidget(pose_group)

        # Connection Group (Hardware)
        conn_group = QGroupBox("Hardware")
        conn_layout = QVBoxLayout()
        
        self.right_layout.addStretch() # Asegura que los grupos no floten si hay espacio

        
        port_layout = QHBoxLayout()
        self.port_selector = QComboBox()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(60)
        self.btn_refresh.clicked.connect(self.refresh_ports)
        port_layout.addWidget(QLabel("Port:"))
        port_layout.addWidget(self.port_selector)
        port_layout.addWidget(self.btn_refresh)
        
        self.btn_connect = QPushButton("Connect Arduino")
        self.btn_connect.clicked.connect(self.toggle_serial)
        self.conn_status = QLabel("Status: Disconnected")
        
        conn_layout.addLayout(port_layout)
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.conn_status)
        conn_group.setLayout(conn_layout)
        self.right_layout.addWidget(conn_group)

    def refresh_ports(self):
        self.port_selector.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_selector.addItem(port.device)
        
        if not ports:
            self.conn_status.setText("No ports found")
        else:
            self.conn_status.setText(f"Found {len(ports)} ports")

    def launch_simulation(self):
        # Obtener el ID de la ventana de Qt para incrustar Ursina
        win_id = str(int(self.sim_container.winId()))
        
        # Pasamos el ancho y alto del contenedor al script de simulación
        width = str(self.sim_container.width())
        height = str(self.sim_container.height())
        
        self.sim_proc = subprocess.Popen([sys.executable, "sim_3d.py", win_id, width, height])
        self.btn_launch_sim.setEnabled(False)
        self.btn_launch_sim.setText("Simulación Iniciada")
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Si la simulación está corriendo, deberíamos avisarle del nuevo tamaño, pero Ursina 
        # embebido en X11/Linux a veces requiere que se fije el tamaño al inicio
        pass

    def toggle_camera(self):
        if not self.camera_active:
            self.cam_thread.running = True
            self.cam_thread.start()
            self.btn_toggle_cam.setText("Desactivar Cámara")
            self.camera_active = True
        else:
            self.cam_thread.stop()
            self.cam_label.setText("Cámara desactivada")
            self.cam_label.setPixmap(QPixmap())
            self.btn_toggle_cam.setText("Activar Cámara")
            self.camera_active = False

    def toggle_serial(self):
        if self.ser is None or not self.ser.is_open:
            selected_port = self.port_selector.currentText()
            if not selected_port:
                self.conn_status.setText("Error: No port selected")
                return
            try:
                self.ser = serial.Serial(selected_port, 115200, timeout=1)
                self.conn_status.setText(f"Connected: {selected_port}")
                self.btn_connect.setText("Disconnect")
                self.port_selector.setEnabled(False)
                self.btn_refresh.setEnabled(False)
            except Exception as e:
                self.conn_status.setText(f"Error: {str(e)}")
        else:
            self.ser.close()
            self.ser = None
            self.conn_status.setText("Status: Disconnected")
            self.btn_connect.setText("Connect Arduino")
            self.port_selector.setEnabled(True)
            self.btn_refresh.setEnabled(True)

    def send_angles(self):
        angles = [s.value() for s in self.sliders]
        # Enviar a simulación 3D
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.target_addr)
        # Enviar a hardware real si está conectado
        if self.ser and self.ser.is_open:
            # Formato: "ANG1,ANG2,ANG3,GRIPPER\n"
            serial_msg = f"{angles[0] + 90},{angles[1] + 90},{angles[2] + 90},0\n"
            self.ser.write(serial_msg.encode())

    def spawn_request(self):
        msg = json.dumps({
            "type": "spawn",
            "shape": self.obj_type.currentText(),
            "size": self.obj_size.value(),
            "mass": self.obj_mass.value()
        })
        self.sock.sendto(msg.encode(), self.target_addr)

    # --- POSE SYSTEM ---
    def save_current_pose(self):
        name, ok = QInputDialog.getText(self, "Guardar Pose", "Nombre de la Pose:")
        if ok and name:
            angles = [s.value() for s in self.sliders]
            thumb_path = os.path.join(self.pose_icons_dir, f"{name}.png")
            
            # Pedir a Ursina que tome un screenshot
            msg = json.dumps({"type": "screenshot", "path": thumb_path})
            self.sock.sendto(msg.encode(), self.target_addr)
            
            # Guardamos datos
            self.saved_poses[name] = angles
            self.save_poses_data()
            
            # Pequeño delay para que Ursina guarde el archivo antes de leerlo
            QTimer.singleShot(500, lambda: self.refresh_pose_gallery())

    def load_poses_data(self):
        if os.path.exists(self.poses_file):
            try:
                with open(self.poses_file, "r") as f:
                    self.saved_poses = json.load(f)
                self.refresh_pose_gallery()
            except: pass

    def save_poses_data(self):
        with open(self.poses_file, "w") as f:
            json.dump(self.saved_poses, f, indent=4)

    def refresh_pose_gallery(self):
        self.pose_list.clear()
        for name, angles in self.saved_poses.items():
            thumb_path = os.path.join(self.pose_icons_dir, f"{name}.png")
            
            # Crear item y su widget custom
            item = QListWidgetItem(self.pose_list)
            item.setText(name)
            item.setSizeHint(QSize(90, 115))
            
            widget = PoseWidget(name, thumb_path, show_delete=False)
            # Para que el doble click funcione en el widget, lo hacemos transparente a eventos o lo manejamos
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            
            self.pose_list.addItem(item)
            self.pose_list.setItemWidget(item, widget)

    def load_pose_item(self, item):
        name = item.text()
        if name in self.saved_poses:
            angles = self.saved_poses[name]
            for i, val in enumerate(angles):
                self.sliders[i].setValue(val)

    def delete_selected_pose(self):
        item = self.pose_list.currentItem()
        if item:
            name = item.text()
            if name in self.saved_poses:
                del self.saved_poses[name]
                self.save_poses_data()
                self.refresh_pose_gallery()

    def add_selected_to_timeline(self):
        item = self.pose_list.currentItem()
        if not item: return
        
        pose_name = item.text()
        thumb_path = os.path.join(self.pose_icons_dir, f"{pose_name}.png")
        
        # Añadir conector de tiempo si ya hay items
        if self.timeline_widgets:
            conn = TimeConnectorWidget()
            self.tl_layout.addWidget(conn)
            self.timeline_widgets.append(conn)
            
        # Añadir step de pose
        step = PoseWidget(pose_name, thumb_path, show_delete=True)
        step.btn_del.clicked.connect(lambda: self.remove_from_timeline(step))
        self.tl_layout.addWidget(step)
        self.timeline_widgets.append(step)
        
    def remove_from_timeline(self, widget):
        # Encontrar el índice
        if widget in self.timeline_widgets:
            idx = self.timeline_widgets.index(widget)
            # Eliminar el widget y su conector previo o siguiente
            if idx > 0 and isinstance(self.timeline_widgets[idx-1], TimeConnectorWidget):
                self.tl_layout.removeWidget(self.timeline_widgets[idx-1])
                self.timeline_widgets[idx-1].deleteLater()
                self.timeline_widgets.pop(idx-1)
                idx -= 1
            elif idx < len(self.timeline_widgets) - 1 and isinstance(self.timeline_widgets[idx+1], TimeConnectorWidget):
                self.tl_layout.removeWidget(self.timeline_widgets[idx+1])
                self.timeline_widgets[idx+1].deleteLater()
                self.timeline_widgets.pop(idx+1)
            
            self.tl_layout.removeWidget(widget)
            widget.deleteLater()
            self.timeline_widgets.pop(idx)

    def clear_visual_timeline(self):
        for w in self.timeline_widgets:
            self.tl_layout.removeWidget(w)
            w.deleteLater()
        self.timeline_widgets = []

    def play_sequence(self):
        # Convertir timeline widgets a lista de poses/tiempos
        self.current_interp_sequence = []
        
        # El primer widget DEBE ser un Step. Los conectores están entre Steps.
        # [Step0, Conn0, Step1, Conn1, Step2]
        
        for i in range(len(self.timeline_widgets)):
            w = self.timeline_widgets[i]
            if isinstance(w, PoseWidget):
                pose_name = w.pose_name
                duration = 0.5 # Default rápido si es el primero
                
                # Buscar el conector PREVIO para saber cuánto tiempo tardar en LLEGAR a esta pose
                if i > 0 and isinstance(self.timeline_widgets[i-1], TimeConnectorWidget):
                    duration = self.timeline_widgets[i-1].time_input.value()
                
                if pose_name in self.saved_poses:
                    self.current_interp_sequence.append({
                        "angles": self.saved_poses[pose_name],
                        "duration": duration
                    })
        
        if self.current_interp_sequence:
            self.current_seq_index = 0
            self.btn_play_seq.setEnabled(False)
            self.start_next_in_sequence()

    def start_next_in_sequence(self):
        if self.current_seq_index >= len(self.current_interp_sequence):
            self.btn_play_seq.setEnabled(True)
            return
            
        target = self.current_interp_sequence[self.current_seq_index]
        self.target_angles = target["angles"]
        duration = target["duration"]
        
        # FPS sim para interpolación (ej: 30 fps)
        fps = 30
        self.interp_steps = int(duration * fps)
        self.interp_count = 0
        
        current_angles = [s.value() for s in self.sliders]
        self.interp_deltas = [
            (self.target_angles[i] - current_angles[i]) / self.interp_steps
            for i in range(3)
        ]
        
        self.interp_timer.start(int(1000/fps))

    def update_interpolation(self):
        self.interp_count += 1
        if self.interp_count <= self.interp_steps:
            for i in range(3):
                # Usar float temporal para precisión si fuera necesario, 
                # pero los sliders son int. Hacemos casting.
                new_val = self.sliders[i].value() + self.interp_deltas[i]
                self.sliders[i].blockSignals(True)
                self.sliders[i].setValue(int(new_val))
                self.sliders[i].blockSignals(False)
            self.send_angles() # Enviar a sim y hardware
        else:
            self.interp_timer.stop()
            # Asegurar valor exacto al final
            for i in range(3):
                self.sliders[i].setValue(self.target_angles[i])
            self.send_angles()
            
            self.current_seq_index += 1
            self.start_next_in_sequence()

    def update_image(self, frame, pose_landmarks_list, hand_landmarks_list):
        h, w, _ = frame.shape
        base_angle = 0
        shoulder_angle = 0
        elbow_angle = 0
        
        # 1. Pose Processing (Shoulder & Elbow)
        if pose_landmarks_list:
            for pose_lms in pose_landmarks_list:
                try:
                    shoulder = pose_lms[12]
                    elbow = pose_lms[14]
                    wrist = pose_lms[16]

                    # Dibujar esqueleto del brazo
                    pts = []
                    for lm in [shoulder, elbow, wrist]:
                        cx, cy = int(lm.x * w), int(lm.y * h)
                        pts.append((cx, cy))
                        cv2.circle(frame, (cx, cy), 5, (0, 255, 0), cv2.FILLED)
                    cv2.line(frame, pts[0], pts[1], (255, 0, 0), 2)
                    cv2.line(frame, pts[1], pts[2], (255, 0, 0), 2)

                    # Hombro (Joint 1)
                    v1 = np.array([elbow.x - shoulder.x, elbow.y - shoulder.y])
                    v_up = np.array([0, -1])
                    unit_v1 = v1 / (np.linalg.norm(v1) + 1e-6)
                    shoulder_angle = int(np.degrees(np.arccos(np.clip(np.dot(unit_v1, v_up), -1.0, 1.0))) - 90)

                    # Codo (Joint 2)
                    v_arm = np.array([shoulder.x - elbow.x, shoulder.y - elbow.y])
                    v_forearm = np.array([wrist.x - elbow.x, wrist.y - elbow.y])
                    unit_arm = v_arm / (np.linalg.norm(v_arm) + 1e-6)
                    unit_forearm = v_forearm / (np.linalg.norm(v_forearm) + 1e-6)
                    elbow_angle = int(180 - np.degrees(np.arccos(np.clip(np.dot(unit_arm, unit_forearm), -1.0, 1.0))))
                    
                    # Fallback para Base si no hay mano
                    base_angle = int((wrist.x - shoulder.x) * -200)
                except: pass

        # 2. Hand Processing (Base Rotation via Palm)
        if hand_landmarks_list:
            for hand_lms in hand_landmarks_list:
                try:
                    # Dibujar puntos de la mano
                    for lm in hand_lms:
                        cx, cy = int(lm.x * w), int(lm.y * h)
                        cv2.circle(frame, (cx, cy), 2, (0, 255, 255), cv2.FILLED)
                    
                    # Calcular rotación de la palma (Vector Muñeca[0] -> Base Dedo Medio[9])
                    wrist_lm = hand_lms[0]
                    middle_mcp = hand_lms[9]
                    
                    # Ángulo en el plano de la imagen
                    dx = middle_mcp.x - wrist_lm.x
                    dy = middle_mcp.y - wrist_lm.y
                    palm_angle = np.degrees(np.arctan2(dy, dx))
                    
                    # Mapear ángulo de la palma a rotación de la base (-180 a 180)
                    # Ajustamos 90 grados para que la mano vertical sea 0
                    base_angle = int(palm_angle + 90)
                except: pass

        if pose_landmarks_list or hand_landmarks_list:
            self.send_camera_angles([
                max(-180, min(180, base_angle)),
                max(-180, min(180, shoulder_angle)),
                max(-180, min(180, elbow_angle))
            ])
            cv2.putText(frame, f"Base (Palm): {base_angle}", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        p = convert_to_Qt_format.scaled(320, 240, Qt.KeepAspectRatio)
        self.cam_label.setPixmap(QPixmap.fromImage(p))

    def send_camera_angles(self, angles):
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.target_addr)

    def sync_from_sim(self):
        try:
            while True:
                data, addr = self.recv_sock.recvfrom(1024)
                msg = json.loads(data.decode())
                if msg.get("type") == "sync_angles":
                    angles = msg["data"]
                    # Bloquear señales para no reenviar a la simulación
                    for i, angle in enumerate(angles):
                        if i < len(self.sliders):
                            self.sliders[i].blockSignals(True)
                            self.sliders[i].setValue(int(angle))
                            self.sliders[i].blockSignals(False)
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"Error en sync_from_sim: {e}")

    def reset_camera_sim(self):
        msg = json.dumps({"type": "reset_camera"})
        self.sock.sendto(msg.encode(), self.target_addr)

    def load_config(self):
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
                    
                    # Restore angles
                    angles = config.get("joint_angles", [0, 0, 0])
                    for i, angle in enumerate(angles):
                        if i < len(self.sliders):
                            self.sliders[i].setValue(angle)
                    
                    # Restore serial port
                    last_port = config.get("serial_port")
                    if last_port:
                        index = self.port_selector.findText(last_port)
                        if index >= 0:
                            self.port_selector.setCurrentIndex(index)
        except Exception as e:
            print(f"Error loading config: {e}")

    def save_config(self):
        try:
            config = {}
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
            
            config["joint_angles"] = [s.value() for s in self.sliders]
            config["serial_port"] = self.port_selector.currentText()
            
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def closeEvent(self, event):
        self.save_config()
        self.cam_thread.stop()
        if self.sim_proc:
            self.sim_proc.terminate()
        if self.ser:
            self.ser.close()
        event.accept()

if __name__ == "__main__":
    import os
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(sys.argv)
    window = RobotGui()
    window.show()
    sys.exit(app.exec())
