"""
gui/widgets.py — Reusable UI widget components.

Classes:
    PoseWidget          — Card showing a pose thumbnail + name + optional delete button.
    TimeConnectorWidget — Horizontal connector with duration spinbox between poses in timeline.
"""
import os
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class PoseWidget(QFrame):
    """Card widget that displays a pose thumbnail, name, and an optional delete button."""

    def __init__(self, pose_name: str, thumb_path: str, parent=None, show_delete: bool = True):
        super().__init__(parent)
        self.pose_name = pose_name
        self.setFixedSize(85, 110)
        self.setStyleSheet(
            "QFrame { background-color: #333; border-radius: 5px; border: 1px solid #555; } "
            "QFrame:hover { border: 1px solid #2196F3; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        if show_delete:
            self.btn_del = QPushButton("×")
            self.btn_del.setFixedSize(18, 18)
            self.btn_del.setStyleSheet(
                "background-color: #c62828; color: white; border-radius: 9px; "
                "font-weight: bold; font-size: 14px;"
            )
            layout.addWidget(self.btn_del, 0, Qt.AlignRight)
        else:
            layout.addSpacing(18)  # Placeholder where delete button would be

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(90, 60)
        if os.path.exists(thumb_path):
            pix = QPixmap(thumb_path).scaled(90, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pix)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("border: none; background: transparent;")

        self.name_label = QLabel(pose_name)
        self.name_label.setStyleSheet(
            "color: white; font-size: 10px; font-weight: bold; border: none;"
        )
        self.name_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.icon_label, 0, Qt.AlignCenter)
        layout.addWidget(self.name_label, 0, Qt.AlignCenter)
        layout.addStretch()


class TimeConnectorWidget(QWidget):
    """Widget showing duration spinner + arrow between poses in the timeline."""

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
