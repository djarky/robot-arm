"""
gui_main.py — Robot Arm Control System — Main entry point.

This file contains only RobotGui (the main window) wired together via mixins.
All feature logic lives in the gui/ subpackage:
    gui/widgets.py           — PoseWidget, TimeConnectorWidget
    gui/camera_thread.py     — CameraThread
    gui/pose_manager.py      — PoseManagerMixin
    gui/animation_manager.py — AnimationManagerMixin
    gui/communication.py     — CommunicationMixin
"""
import os
import sys
import socket
import subprocess

import cv2
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QSlider, QListWidget, QFrame,
    QScrollArea, QSizePolicy, QComboBox, QDoubleSpinBox,
    QFormLayout
)
from PySide6.QtCore import QTimer, Qt, QSize
from PySide6.QtGui import QImage, QPixmap

from gui.widgets import PoseWidget, TimeConnectorWidget
from gui.camera_thread import CameraThread
from gui.pose_manager import PoseManagerMixin
from gui.animation_manager import AnimationManagerMixin
from gui.communication import CommunicationMixin


class RobotGui(CommunicationMixin, PoseManagerMixin, AnimationManagerMixin, QMainWindow):
    """Main application window.

    Inherits feature mixins for communication, pose management, and animation.
    Responsible only for window layout, lifecycle, and camera integration.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Robot Arm Control System")
        self.resize(1200, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # === UDP sockets ===
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_addr = ("127.0.0.1", 5005)

        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.recv_sock.bind(("127.0.0.1", 5006))
            self.recv_sock.setblocking(False)
        except Exception as e:
            print(f"No se pudo enlazar el puerto de feedback: {e}")

        # Timer for UDP feedback polling (every 50 ms)
        self.feedback_timer = QTimer()
        self.feedback_timer.timeout.connect(self.sync_from_sim)
        self.feedback_timer.start(50)

        # Process / serial handles
        self.ser = None
        self.sim_proc = None

        # === Left panel: 3-D Simulation ===
        self.sim_panel = QGroupBox("3D Simulation View")
        sim_layout = QVBoxLayout()

        self.setup_sim_top_panel(sim_layout)

        self.sim_container = QWidget()
        self.sim_container.setStyleSheet("background-color: black;")
        self.sim_container.setMinimumSize(600, 200)

        sim_layout.addWidget(self.sim_container)

        # Visual timeline (from AnimationManagerMixin)
        self.setup_visual_timeline(sim_layout)

        button_layout = QHBoxLayout()
        self.btn_launch_sim = QPushButton("Lanzar Simulación 3D (Ursina)")
        self.btn_launch_sim.clicked.connect(self.launch_simulation)
        self.btn_reset_cam = QPushButton("Reset View")
        self.btn_reset_cam.clicked.connect(self.reset_camera_sim)
        
        self.playback_mode = QComboBox()
        self.playback_mode.addItems(["Una Vez", "Bucle", "Ping-Pong"])
        self.playback_mode.setToolTip("Modo de repetición de la animación")
        
        self.btn_play_seq = QPushButton("▶ REPRODUCIR SECUENCIA")
        self.btn_play_seq.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;"
        )
        self.btn_play_seq.clicked.connect(self.play_sequence)

        button_layout.addWidget(self.btn_launch_sim)
        button_layout.addWidget(self.btn_reset_cam)
        button_layout.addWidget(self.playback_mode)
        button_layout.addWidget(self.btn_play_seq)

        sim_layout.addLayout(button_layout)
        sim_layout.setStretch(0, 0)   # Spawn top panel
        sim_layout.setStretch(1, 10)  # Sim container
        sim_layout.setStretch(2, 0)   # Timeline
        sim_layout.setStretch(3, 0)   # Buttons

        self.sim_panel.setLayout(sim_layout)
        self.main_layout.addWidget(self.sim_panel, 7)

        # === Right panel: Camera + Controls (with scroll) ===
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(5, 5, 5, 5)
        self.right_scroll.setWidget(self.right_panel)

        self.main_layout.addWidget(self.right_scroll, 3)

        self.setup_camera_panel()
        self.setup_control_panel()

        # === Initialise subsystems ===
        self.refresh_ports()
        self.load_config()

        self.cam_thread = CameraThread()
        self.cam_thread.image_update.connect(self.update_image)
        self.camera_active = False

        # Pose data
        self.poses_file = os.path.join(os.getcwd(), "poses.json")
        self.saved_poses = {}
        self.pose_icons_dir = "pose_thumbnails"
        if not os.path.exists(self.pose_icons_dir):
            os.makedirs(self.pose_icons_dir)
        
        print(f"SISTEMA DETECTADO: {sys.platform}")
        self.load_poses_data()

        # Animation data
        self.animations_file = os.path.join(os.getcwd(), "animations.json")
        self.saved_animations = {}
        self.load_animations_data()

        # Interpolation engine state
        self.interp_timer = QTimer()
        self.interp_timer.timeout.connect(self.update_interpolation)
        self.target_angles = [0, 0, 0, 0, 0, 0]
        self.current_interp_sequence = []
        self.current_seq_index = -1
        self.interp_steps = 0
        self.interp_count = 0
        self.interp_deltas = [0, 0, 0, 0, 0, 0]
        self.current_angles_f = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.playback_direction = 1

        # Camera smoothing state
        self.smooth_camera_angles = [0.0, 0.0, 0.0]  # Solo 3 ejes para tracking de cámara
        self.camera_active_last_frame = False

    # ------------------------------------------------------------------
    # Panel builders
    # ------------------------------------------------------------------

    def setup_sim_top_panel(self, parent_layout):
        """Build the spawn-object row at the top of the simulation panel."""
        spawn_row = QHBoxLayout()
        spawn_row.addWidget(QLabel("Spawn:"))
        self.obj_type = QComboBox()
        self.obj_type.addItems(["cube", "cylinder", "sphere", "torus"])
        self.obj_size = QDoubleSpinBox()
        self.obj_size.setValue(0.5)
        self.obj_size.setSingleStep(0.1)
        self.obj_mass = QDoubleSpinBox()
        self.obj_mass.setValue(1.0)
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

    def setup_camera_panel(self):
        """Build the camera preview group on the right panel."""
        group = QGroupBox("Camera Tracking")
        layout = QVBoxLayout()

        self.cam_label = QLabel("Cámara desactivada")
        self.cam_label.setAlignment(Qt.AlignCenter)
        self.cam_label.setFixedSize(400, 300)
        self.cam_label.setStyleSheet(
            "background-color: black; color: white; border-radius: 5px;"
        )

        self.btn_toggle_cam = QPushButton("Activar Seguimiento")
        self.btn_toggle_cam.clicked.connect(self.toggle_camera)

        self.cam_status_label = QLabel("SISTEMA: DESACTIVADO")
        self.cam_status_label.setAlignment(Qt.AlignCenter)
        self.cam_status_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; padding: 2px; background-color: #222; color: #666; border-radius: 2px;"
        )

        layout.addWidget(self.cam_label)
        layout.addWidget(self.cam_status_label)
        layout.addWidget(self.btn_toggle_cam)
        group.setLayout(layout)
        self.right_layout.addWidget(group)

    def setup_control_panel(self):
        """Build manual joint sliders, pose gallery, and hardware connection group."""
        # --- Manual joint sliders ---
        joint_group = QGroupBox("Manual Control")
        joint_layout = QFormLayout()
        self.sliders = []
        joint_labels = ["J0", "J1", "J2", "J3", "J4", "J5"]
        for i in range(6):
            s = QSlider(Qt.Horizontal)
            s.setRange(-90, 90)
            s.setValue(0)
            s.valueChanged.connect(self.send_angles)
            joint_layout.addRow(f"{joint_labels[i]}:", s)
            self.sliders.append(s)
        joint_group.setLayout(joint_layout)
        self.right_layout.addWidget(joint_group)

        # --- Pose gallery ---
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
        self.pose_list.setDragEnabled(False)
        self.pose_list.setAcceptDrops(False)
        self.pose_list.setDragDropMode(QListWidget.NoDragDrop)

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

        self.right_layout.addStretch()

        # --- Hardware connection ---
        conn_group = QGroupBox("Hardware")
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
        
        self.packet_status = QLabel("RX: --")
        self.packet_status.setAlignment(Qt.AlignCenter)
        self.packet_status.setStyleSheet("color: #666; font-size: 10px;")

        conn_layout.addLayout(port_layout)
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.conn_status)
        conn_layout.addWidget(self.packet_status)
        conn_group.setLayout(conn_layout)
        self.right_layout.addWidget(conn_group)

    def on_packet_received(self, success, error_msg=None):
        """Visual feedback when a packet is confirmed by Arduino."""
        if success:
            self.packet_status.setText("RX: OK")
            self.packet_status.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 10px;")
            # Flash effect
            QTimer.singleShot(200, lambda: self.packet_status.setStyleSheet("color: #666; font-size: 10px;"))
        else:
            self.packet_status.setText(f"RX: ERR")
            self.packet_status.setStyleSheet("color: #f44336; font-weight: bold; font-size: 10px;")
            print(f"Arduino Error: {error_msg}")

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def launch_simulation(self):
        """Launch the Ursina 3-D simulation embedded in sim_container."""
        win_id = str(int(self.sim_container.winId()))
        width = str(self.sim_container.width())
        height = str(self.sim_container.height())
        if getattr(sys, 'frozen', False):
            sim_executable = os.path.join(os.path.dirname(sys.executable), 'sim_3d')
            if sys.platform == 'win32':
                sim_executable += '.exe'
            self.sim_proc = subprocess.Popen(
                [sim_executable, win_id, width, height]
            )
        else:
            self.sim_proc = subprocess.Popen(
                [sys.executable, "sim_3d.py", win_id, width, height]
            )
        self.btn_launch_sim.setEnabled(False)
        self.btn_launch_sim.setText("Simulación Iniciada")

    # ------------------------------------------------------------------
    # Camera integration
    # ------------------------------------------------------------------

    def toggle_camera(self):
        """Start or stop the background camera thread."""
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

    def update_image(self, frame_in, pose_landmarks_list, hand_landmarks_list):
        """Process a camera frame with smoothing and visibility validation."""
        # Force a copy to avoid race conditions with the camera thread buffer
        frame = frame_in.copy()
        h_f, w_f, _ = frame.shape
        
        # Default angles if no detection (persistence)
        base_angle = self.smooth_camera_angles[0]
        shoulder_angle = self.smooth_camera_angles[1]
        elbow_angle = self.smooth_camera_angles[2]
        
        arm_visible = False
        low_confidence = False
        
        # Check if animation is currently playing
        # If playing, we skip logic layer to prevent fighting with the interpolation engine
        is_playing = self.interp_timer.isActive()
        
        # 1. Logic Layer: Extract data
        if not is_playing and pose_landmarks_list:
            for pose_lms in pose_landmarks_list:
                try:
                    j_shoulder = pose_lms[12]
                    j_elbow = pose_lms[14]
                    j_wrist = pose_lms[16]
                    
                    # Validation
                    threshold = 0.5
                    if (j_shoulder.visibility < threshold or 
                        j_elbow.visibility < threshold or 
                        j_wrist.visibility < threshold):
                        low_confidence = True
                        continue
                    
                    arm_visible = True

                    # Calculate target angles...
                    v1 = np.array([j_elbow.x - j_shoulder.x, j_elbow.y - j_shoulder.y])
                    v_up = np.array([0, -1])
                    unit_v1 = v1 / (np.linalg.norm(v1) + 1e-6)
                    target_shoulder = int(np.degrees(np.arccos(np.clip(np.dot(unit_v1, v_up), -1.0, 1.0))) - 90)

                    v_arm = np.array([j_shoulder.x - j_elbow.x, j_shoulder.y - j_elbow.y])
                    v_forearm = np.array([j_wrist.x - j_elbow.x, j_wrist.y - j_elbow.y])
                    unit_arm = v_arm / (np.linalg.norm(v_arm) + 1e-6)
                    unit_forearm = v_forearm / (np.linalg.norm(v_forearm) + 1e-6)
                    target_elbow = int(180 - np.degrees(np.arccos(np.clip(np.dot(unit_arm, unit_forearm), -1.0, 1.0))))

                    # Increase multiplier (from 2 to 4) to make it more sensitive
                    dy_normalized = (j_wrist.y - j_shoulder.y) * 4
                    target_base = int(np.clip(dy_normalized * 90, -90, 90))

                    # Apply smoothing and Invert Angles (as requested)
                    MAX_STEP = 10.0
                    EMA_ALPHA = 0.2
                    # Inverting all angles by negating them
                    targets = [-target_base, -target_shoulder, -target_elbow]
                    
                    if not self.camera_active_last_frame:
                         self.smooth_camera_angles = [float(t) for t in targets]
                         self.camera_active_last_frame = True

                    for i in range(3):
                        diff = targets[i] - self.smooth_camera_angles[i]
                        step = np.clip(diff, -MAX_STEP, MAX_STEP)
                        self.smooth_camera_angles[i] = (self.smooth_camera_angles[i] + step) * EMA_ALPHA + \
                                                       self.smooth_camera_angles[i] * (1 - EMA_ALPHA)

                    base_angle, shoulder_angle, elbow_angle = [int(a) for a in self.smooth_camera_angles]
                    
                    # 2. Drawing Layer: Skeleton (Below status bar)
                    pts = []
                    for lm in [j_shoulder, j_elbow, j_wrist]:
                        cx, cy = int(lm.x * w_f), int(lm.y * h_f)
                        pts.append((cx, cy))
                        cv2.circle(frame, (cx, cy), 6, (0, 255, 0), cv2.FILLED)
                    cv2.line(frame, pts[0], pts[1], (255, 255, 0), 2)
                    cv2.line(frame, pts[1], pts[2], (255, 255, 0), 2)
                    
                except Exception as e:
                    print(f"Error procesando frame: {e}")

        # --- 3. UI Status Update (External Label) ---
        if is_playing:
            status_msg = "SISTEMA: REPRODUCIENDO ANIMACIÓN"
            status_style = "background-color: #fbc02d; color: #000000; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
            self.camera_active_last_frame = False
        elif arm_visible:
            status_msg = "SISTEMA: SEGUIMIENTO ACTIVO"
            status_style = "background-color: #1b5e20; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
            
            # Forward camera angles directly to the manual sliders.
            # We block signals temporarily to avoid causing an infinite feedback loop during this block,
            # but we explicitly call send_angles to push the state to BOTH Sim and Arduino.
            angles = [base_angle, shoulder_angle, elbow_angle]
            for i, angle in enumerate(angles):
                if i < len(self.sliders):
                    self.sliders[i].blockSignals(True)
                    self.sliders[i].setValue(angle)
                    self.sliders[i].blockSignals(False)
            self.send_angles()
            
        elif low_confidence:
            status_msg = "SISTEMA: BAJA CONFIANZA"
            status_style = "background-color: #e65100; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
            self.camera_active_last_frame = False
        else:
            status_msg = "SISTEMA: NO DETECTADO"
            status_style = "background-color: #b71c1c; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
            self.camera_active_last_frame = False

        self.cam_status_label.setText(status_msg)
        self.cam_status_label.setStyleSheet(status_style)

        # Update UI
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
        self.cam_label.setPixmap(QPixmap.fromImage(qt_image.scaled(400, 300, Qt.KeepAspectRatio)))

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def closeEvent(self, event):
        self.save_config()
        self.cam_thread.stop()
        if self.sim_proc:
            self.sim_proc.terminate()
        if self.ser:
            self.ser.close()
        event.accept()


if __name__ == "__main__":
    if sys.platform == "linux" or sys.platform == "linux2":
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    
    app = QApplication(sys.argv)
    window = RobotGui()
    window.show()
    sys.exit(app.exec())
