from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QGroupBox, 
    QSlider, QListWidget, QComboBox, QDoubleSpinBox, QFormLayout
)
from PySide6.QtCore import Qt, QSize

class LayoutMixin:
    """Mixin that handles the UI building methods for RobotGui."""

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
