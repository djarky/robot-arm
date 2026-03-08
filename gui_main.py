import sys
import cv2
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QDockWidget, 
                             QFormLayout, QDoubleSpinBox, QComboBox, QGroupBox, QSlider)
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
import mediapipe as mp
import subprocess
import json
import socket
import serial
import serial.tools.list_ports

class CameraThread(QThread):
    image_update = Signal(np.ndarray, list)

    def __init__(self):
        super().__init__()
        self.running = True
        self.model_path = 'hand_landmarker.task'

    def run(self):
        # Importación diferida para evitar conflictos con hilos
        import mediapipe as mp
        BaseOptions = mp.tasks.BaseOptions
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.model_path),
            running_mode=VisionRunningMode.IMAGE,
            num_hands=2
        )
        
        cap = cv2.VideoCapture(0)
        with HandLandmarker.create_from_options(options) as landmarker:
            while self.running:
                success, frame = cap.read()
                if success:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    result = landmarker.detect(mp_image)
                    
                    landmarks = []
                    if result.hand_landmarks:
                        landmarks = result.hand_landmarks
                        
                    self.image_update.emit(frame, landmarks)
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

        # Socket para comunicación con la simulación
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_addr = ("127.0.0.1", 5005)

        # Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Subprocess management
        self.ser = None
        self.sim_proc = None

        # Left Panel: 3D Simulation Control
        self.sim_panel = QGroupBox("3D Simulation View")
        sim_layout = QVBoxLayout()
        
        self.sim_container = QWidget()
        self.sim_container.setStyleSheet("background-color: black;")
        self.sim_container.setMinimumSize(600, 400)
        
        self.btn_launch_sim = QPushButton("Lanzar Simulación 3D (Ursina)")
        self.btn_launch_sim.clicked.connect(self.launch_simulation)
        
        self.btn_reset_cam = QPushButton("Reset View")
        self.btn_reset_cam.clicked.connect(self.reset_camera_sim)
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.btn_launch_sim)
        button_layout.addWidget(self.btn_reset_cam)
        
        sim_layout.addWidget(self.sim_container)
        sim_layout.addLayout(button_layout)
        self.sim_panel.setLayout(sim_layout)
        self.main_layout.addWidget(self.sim_panel, 7)

        # Right Panel: Camera and Controls
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.main_layout.addWidget(self.right_panel, 3)

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

    def setup_camera_panel(self):
        group = QGroupBox("Camera Tracking")
        layout = QVBoxLayout()
        self.cam_label = QLabel("Cámara desactivada")
        self.cam_label.setAlignment(Qt.AlignCenter)
        self.cam_label.setFixedSize(320, 240)
        self.cam_label.setStyleSheet("background-color: black; color: white;")
        
        self.btn_toggle_cam = QPushButton("Activar Cámara")
        self.btn_toggle_cam.clicked.connect(self.toggle_camera)
        
        layout.addWidget(self.cam_label)
        layout.addWidget(self.btn_toggle_cam)
        group.setLayout(layout)
        self.right_layout.addWidget(group)

    def setup_control_panel(self):
        # Joint Sliders (Mouse Fallback)
        joint_group = QGroupBox("Manual Control (Sliders)")
        joint_layout = QFormLayout()
        self.sliders = []
        for i in range(3):
            s = QSlider(Qt.Horizontal)
            s.setRange(-180, 180)
            s.setValue(0)
            s.valueChanged.connect(self.send_angles)
            joint_layout.addRow(f"Articulación {i+1}:", s)
            self.sliders.append(s)
        joint_group.setLayout(joint_layout)
        self.right_layout.addWidget(joint_group)

        # Spawning Group
        spawn_group = QGroupBox("Spawn Objects")
        spawn_layout = QFormLayout()
        self.obj_type = QComboBox()
        self.obj_type.addItems(["cube", "cylinder"])
        self.obj_size = QDoubleSpinBox(); self.obj_size.setValue(1.0)
        self.obj_mass = QDoubleSpinBox(); self.obj_mass.setValue(1.0)
        self.btn_spawn = QPushButton("Spawn Object")
        self.btn_spawn.clicked.connect(self.spawn_request)
        spawn_layout.addRow("Tipo:", self.obj_type)
        spawn_layout.addRow("Escala:", self.obj_size)
        spawn_layout.addRow("Masa:", self.obj_mass)
        spawn_layout.addWidget(self.btn_spawn)
        spawn_group.setLayout(spawn_layout)
        self.right_layout.addWidget(spawn_group)

        # Connection Group (Hardware)
        conn_group = QGroupBox("Hardware Control (Arduino)")
        conn_layout = QVBoxLayout()
        
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

    def update_image(self, frame, landmarks):
        if landmarks:
            h, w, _ = frame.shape
            for hand_lms in landmarks:
                # Dibujar esqueleto básico
                for lm in hand_lms:
                    cx, cy = int(lm.x * w), int(lm.y * h)
                    cv2.circle(frame, (cx, cy), 3, (0, 255, 0), cv2.FILLED)
                
                # Mapear gestos (Ejemplo simple base)
                # Usamos el x del landmark 0 para la rotación base
                base_angle = int((hand_lms[0].x - 0.5) * -180)
                # Usamos y del landmark 8 para el brazo
                arm_angle = int((hand_lms[8].y - 0.5) * 180)
                
                # Enviar a simulación
                self.send_camera_angles([base_angle, arm_angle, 0])

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        p = convert_to_Qt_format.scaled(320, 240, Qt.KeepAspectRatio)
        self.cam_label.setPixmap(QPixmap.fromImage(p))

    def send_camera_angles(self, angles):
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.target_addr)

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
