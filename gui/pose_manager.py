"""
gui/pose_manager.py — Mixin providing pose gallery data management.

Classes:
    PoseManagerMixin — Methods for saving, loading, refreshing, and deleting poses.
                       Designed to be mixed into RobotGui (QMainWindow subclass).
"""
import os
import json
from PySide6.QtWidgets import QInputDialog, QListWidgetItem
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap

from gui.widgets import PoseWidget


class PoseManagerMixin:
    """Mixin that adds pose gallery persistence and UI management to the main window.

    Expects the host class to provide:
        self.poses_file        (str)          — path to poses.json
        self.saved_poses       (dict)         — {name: [a, b, c]}
        self.pose_icons_dir    (str)          — directory for pose thumbnails
        self.pose_list         (QListWidget)  — gallery widget
        self.sliders           (list)         — joint slider list
        self.sock              (socket)       — UDP socket to simulation
        self.target_addr       (tuple)        — UDP destination address
    """

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_poses_data(self):
        """Load poses from JSON file and refresh the gallery."""
        if os.path.exists(self.poses_file):
            try:
                with open(self.poses_file, "r") as f:
                    self.saved_poses = json.load(f)
                self.refresh_pose_gallery()
            except Exception:
                pass

    def save_poses_data(self):
        """Persist the current poses dict to JSON."""
        with open(self.poses_file, "w") as f:
            json.dump(self.saved_poses, f, indent=4)

    # ------------------------------------------------------------------
    # Gallery UI
    # ------------------------------------------------------------------

    def refresh_pose_gallery(self):
        """Rebuild the pose list widget from saved_poses."""
        self.pose_list.clear()
        for name in self.saved_poses:
            thumb_path = os.path.join(self.pose_icons_dir, f"{name}.png")

            item = QListWidgetItem(self.pose_list)
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(90, 115))

            widget = PoseWidget(name, thumb_path, show_delete=False)
            # Make transparent so double-click on the item is still detected
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)

            self.pose_list.addItem(item)
            self.pose_list.setItemWidget(item, widget)

    def load_pose_item(self, item):
        """Apply a pose from the gallery to the sliders."""
        name = item.data(Qt.UserRole)
        if name in self.saved_poses:
            angles = self.saved_poses[name]
            for i, val in enumerate(angles):
                self.sliders[i].setValue(val)

    def delete_selected_pose(self):
        """Remove the currently selected pose from gallery and disk."""
        item = self.pose_list.currentItem()
        if item:
            name = item.data(Qt.UserRole)
            if name in self.saved_poses:
                del self.saved_poses[name]
                self.save_poses_data()
                self.refresh_pose_gallery()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def save_current_pose(self):
        """Ask for a name, capture slider angles, request screenshot from Ursina, save."""
        import json as _json
        name, ok = QInputDialog.getText(self, "Guardar Pose", "Nombre de la Pose:")
        if ok and name:
            angles = [s.value() for s in self.sliders]
            thumb_path = os.path.abspath(
                os.path.join(self.pose_icons_dir, f"{name}.png")
            )
            print(f"DEBUG: Solicitando screenshot en: {thumb_path}")

            # Ask Ursina simulation to take a screenshot
            msg = _json.dumps({"type": "screenshot", "path": thumb_path})
            self.sock.sendto(msg.encode(), self.target_addr)

            self.saved_poses[name] = angles
            self.save_poses_data()

            # 1 s delay to let Ursina write the file before reading it
            QTimer.singleShot(1000, self.refresh_pose_gallery)
