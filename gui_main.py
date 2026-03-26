import os
import sys
import socket

import cv2
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QGroupBox, QFrame, QScrollArea, QComboBox
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap

from gui import (
    PoseWidget, TimeConnectorWidget, CameraThread,
    PoseManagerMixin, AnimationManagerMixin, CommunicationMixin,
    LayoutMixin, CameraProcessorMixin
)


class RobotGui(CommunicationMixin, PoseManagerMixin, AnimationManagerMixin, 
               LayoutMixin, CameraProcessorMixin, QMainWindow):
    """Main application window.

    Inherits feature mixins for communication, pose management, animation,
    layout building, and camera logic.
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
        self._waiting_for_path = False

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
        self.smooth_camera_angles = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # 6 ejes para tracking de cámara
        self.camera_active_last_frame = False
        self.is_left_handed = False

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

    def toggle_handedness(self):
        """Switch between right-hand and left-hand camera control modes."""
        self.is_left_handed = not self.is_left_handed
        if self.is_left_handed:
            self.btn_handedness.setText("Modo: Zurdo (Izquierda)")
            self.btn_handedness.setStyleSheet(
                "background-color: #6a1b9a; color: white; border-radius: 3px; padding: 2px;"
            )
        else:
            self.btn_handedness.setText("Modo: Diestro (Derecha)")
            self.btn_handedness.setStyleSheet(
                "background-color: #0d47a1; color: white; border-radius: 3px; padding: 2px;"
            )

    def update_image(self, frame_in, pose_landmarks_list, hand_landmarks_list):
        """Process a camera frame via CameraProcessorMixin and update UI."""
        is_playing = self.interp_timer.isActive()
        
        # 1. Process data (Logic + Drawing) via Mixin
        frame, angles, arm_visible, low_confidence = self.process_pose_data(
            frame_in, pose_landmarks_list, hand_landmarks_list, is_playing, self.is_left_handed
        )
        
        # 2. Update Simulation/Arduino if tracking is active
        if not is_playing and arm_visible:
            # angles contains [base, shoulder, elbow, j3, j4, j5]
            for i, angle in enumerate(angles):
                if i < len(self.sliders):
                    self.sliders[i].blockSignals(True)
                    self.sliders[i].setValue(angle)
                    self.sliders[i].blockSignals(False)
            self.send_angles()
        elif not arm_visible:
            self.camera_active_last_frame = False

        # 3. Update UI Status
        status_msg, status_style = self.get_camera_status_ui(is_playing, arm_visible, low_confidence)
        self.cam_status_label.setText(status_msg)
        self.cam_status_label.setStyleSheet(status_style)

        # 4. Convert and display image
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
