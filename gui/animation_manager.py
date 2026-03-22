"""
gui/animation_manager.py — Mixin providing timeline UI + animation/interpolation logic.

Classes:
    AnimationManagerMixin — Methods for the visual timeline, pose sequencing,
                            animation save/load/delete, and interpolation playback.
                            Designed to be mixed into RobotGui (QMainWindow subclass).
"""
import os
import json
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from gui.widgets import PoseWidget, TimeConnectorWidget


class AnimationManagerMixin:
    """Mixin that adds visual timeline and animation playback to the main window.

    Expects the host class to provide:
        self.saved_poses            (dict)          — {name: [a, b, c, d, e]}
        self.saved_animations       (dict)          — {name: [{pose, duration}, ...]}
        self.animations_file        (str)           — path to animations.json
        self.pose_icons_dir         (str)           — directory for thumbnails
        self.sliders                (list)          — joint slider list
        self.interp_timer           (QTimer)        — interpolation timer
        self.current_interp_sequence(list)          — sequence being played
        self.current_seq_index      (int)           — current step index
        self.interp_steps           (int)           — total interpolation steps
        self.interp_count           (int)           — current interpolation step count
        self.interp_deltas          (list[float])   — per-joint delta per step
        self.current_angles_f       (list[float])   — current angles as floats
        self.target_angles          (list)          — target angles for current step
        self.sim_panel              (QGroupBox)     — parent panel (for layout invalidation)
        self.btn_play_seq           (QPushButton)   — play button reference
    """

    # ------------------------------------------------------------------
    # Timeline setup
    # ------------------------------------------------------------------

    def setup_visual_timeline(self, parent_layout):
        """Build the collapsible visual timeline widget and add it to parent_layout."""
        self.timeline_group = QGroupBox("Timeline de Movimiento")
        tl_main_vbox = QVBoxLayout()
        tl_main_vbox.setContentsMargins(5, 2, 5, 5)
        tl_main_vbox.setSpacing(0)

        # --- Header row ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self.btn_toggle_tl = QPushButton("▼")
        self.btn_toggle_tl.setFixedSize(30, 20)
        self.btn_toggle_tl.clicked.connect(self.toggle_timeline)
        header_layout.addWidget(self.btn_toggle_tl)

        header_layout.addWidget(QLabel("Anim:"))

        self.anim_selector = QComboBox()
        self.anim_selector.setMinimumWidth(100)
        self.anim_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_layout.addWidget(self.anim_selector)

        self.btn_save_anim = QPushButton("Guardar")
        self.btn_save_anim.setFixedWidth(58)
        self.btn_save_anim.setStyleSheet(
            "background-color: #388E3C; color: white; font-size: 11px;"
        )
        self.btn_save_anim.clicked.connect(self.save_animation)
        header_layout.addWidget(self.btn_save_anim)

        self.btn_load_anim = QPushButton("Cargar")
        self.btn_load_anim.setFixedWidth(52)
        self.btn_load_anim.setStyleSheet(
            "background-color: #1976D2; color: white; font-size: 11px;"
        )
        self.btn_load_anim.clicked.connect(self.load_animation)
        header_layout.addWidget(self.btn_load_anim)

        self.btn_del_anim = QPushButton("Del")
        self.btn_del_anim.setFixedWidth(36)
        self.btn_del_anim.setStyleSheet(
            "background-color: #c62828; color: white; font-size: 11px;"
        )
        self.btn_del_anim.clicked.connect(self.delete_animation)
        header_layout.addWidget(self.btn_del_anim)

        # --- Collapsible container ---
        self.tl_container_widget = QWidget()
        self.tl_container_layout = QHBoxLayout(self.tl_container_widget)
        self.tl_container_layout.setContentsMargins(0, 2, 0, 0)

        # Horizontal scroll area for the timeline track
        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidgetResizable(True)
        self.tl_scroll.setFixedHeight(150)
        self.tl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.tl_content = QWidget()
        self.tl_layout = QHBoxLayout(self.tl_content)
        self.tl_layout.setAlignment(Qt.AlignLeft)
        self.tl_scroll.setWidget(self.tl_content)

        # Sidebar controls
        self.tl_side_controls = QWidget()
        side_ctrl_layout = QVBoxLayout(self.tl_side_controls)
        side_ctrl_layout.setContentsMargins(5, 0, 0, 0)

        self.btn_add_tl = QPushButton("+")
        self.btn_add_tl.setFixedSize(40, 40)
        self.btn_add_tl.setStyleSheet(
            "font-size: 24px; font-weight: bold; background-color: #2196F3; "
            "color: white; border-radius: 20px;"
        )
        self.btn_add_tl.clicked.connect(self.add_selected_to_timeline)

        self.btn_clear_tl = QPushButton("Clear")
        self.btn_clear_tl.setFixedWidth(50)
        self.btn_clear_tl.clicked.connect(self.clear_visual_timeline)

        side_ctrl_layout.addWidget(self.btn_add_tl)
        side_ctrl_layout.addWidget(self.btn_clear_tl)

        self.tl_container_layout.addWidget(self.tl_scroll)
        self.tl_container_layout.addWidget(self.tl_side_controls)

        self.tl_container_widget.hide()  # Minimize by default

        tl_main_vbox.addLayout(header_layout)
        tl_main_vbox.addWidget(self.tl_container_widget)

        self.timeline_group.setLayout(tl_main_vbox)
        self.timeline_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        parent_layout.addWidget(self.timeline_group)
        self.timeline_widgets = []

    def toggle_timeline(self):
        """Show/hide the timeline track area."""
        is_visible = self.tl_container_widget.isVisible()
        self.tl_container_widget.setVisible(not is_visible)
        self.btn_toggle_tl.setText("▲" if is_visible else "▼")
        self.sim_panel.layout().invalidate()
        self.sim_panel.layout().activate()

    # ------------------------------------------------------------------
    # Timeline track management
    # ------------------------------------------------------------------

    def add_selected_to_timeline(self):
        """Add the currently selected gallery pose as a new step on the timeline."""
        item = self.pose_list.currentItem()
        if not item:
            return
        pose_name = item.data(Qt.UserRole)
        thumb_path = os.path.join(self.pose_icons_dir, f"{pose_name}.png")

        if not self.timeline_widgets:
            conn_start = TimeConnectorWidget(arrow_text="▶")
            self.tl_layout.addWidget(conn_start)
            self.timeline_widgets.append(conn_start)

            step = PoseWidget(pose_name, thumb_path, show_delete=True)
            step.btn_del.clicked.connect(lambda checked=False, sw=step: self.remove_from_timeline(sw))
            self.tl_layout.addWidget(step)
            self.timeline_widgets.append(step)

            conn_end = TimeConnectorWidget(arrow_text="↺")
            self.tl_layout.addWidget(conn_end)
            self.timeline_widgets.append(conn_end)
        else:
            conn_new = TimeConnectorWidget(arrow_text="→")
            step = PoseWidget(pose_name, thumb_path, show_delete=True)
            step.btn_del.clicked.connect(lambda checked=False, sw=step: self.remove_from_timeline(sw))

            # Remove end connector temporarily
            conn_end = self.timeline_widgets.pop()
            self.tl_layout.removeWidget(conn_end)

            self.tl_layout.addWidget(conn_new)
            self.timeline_widgets.append(conn_new)

            self.tl_layout.addWidget(step)
            self.timeline_widgets.append(step)

            self.tl_layout.addWidget(conn_end)
            self.timeline_widgets.append(conn_end)

    def remove_from_timeline(self, widget):
        """Remove a pose step (and its preceding connector) from the timeline."""
        if widget not in self.timeline_widgets:
            return
        
        if len(self.timeline_widgets) <= 3:
            # Only start, pose, end remaining. Clear all.
            self.clear_visual_timeline()
            return
            
        idx = self.timeline_widgets.index(widget)

        # Remove the preceding connector
        conn_to_remove = self.timeline_widgets[idx - 1]
        self.tl_layout.removeWidget(conn_to_remove)
        conn_to_remove.deleteLater()
        self.timeline_widgets.pop(idx - 1)
        idx -= 1

        # Remove the pose
        self.tl_layout.removeWidget(widget)
        widget.deleteLater()
        self.timeline_widgets.pop(idx)
        
        # Ensure the first connector always has the start arrow
        if self.timeline_widgets:
            self.timeline_widgets[0].arrow.setText("▶")

    def clear_visual_timeline(self):
        """Remove all items from the visual timeline."""
        for w in self.timeline_widgets:
            self.tl_layout.removeWidget(w)
            w.deleteLater()
        self.timeline_widgets = []

    # ------------------------------------------------------------------
    # Animation persistence
    # ------------------------------------------------------------------

    def load_animations_data(self):
        """Load saved animations from JSON and populate the animation selector."""
        if os.path.exists(self.animations_file):
            try:
                with open(self.animations_file, "r") as f:
                    self.saved_animations = json.load(f)
                self._refresh_anim_selector()
            except Exception:
                pass

    def _refresh_anim_selector(self):
        """Rebuild animation combo-box from saved_animations dict."""
        self.anim_selector.clear()
        for name in self.saved_animations:
            self.anim_selector.addItem(name)

    def save_animation(self):
        """Serialize the current timeline into a named animation and persist it."""
        from PySide6.QtWidgets import QInputDialog

        sequence = []
        for i, w in enumerate(self.timeline_widgets):
            if isinstance(w, PoseWidget):
                duration = self.timeline_widgets[i - 1].time_input.value()
                sequence.append({"pose": w.pose_name, "duration": duration})

        if not sequence:
            return
            
        if self.timeline_widgets and isinstance(self.timeline_widgets[-1], TimeConnectorWidget):
            sequence.append({"pose": None, "duration": self.timeline_widgets[-1].time_input.value()})

        name, ok = QInputDialog.getText(self, "Guardar Animación", "Nombre de la animación:")
        if ok and name:
            self.saved_animations[name] = sequence
            with open(self.animations_file, "w") as f:
                json.dump(self.saved_animations, f, indent=4)
            self._refresh_anim_selector()
            idx = self.anim_selector.findText(name)
            if idx >= 0:
                self.anim_selector.setCurrentIndex(idx)

    def load_animation(self):
        """Load the selected animation from saved_animations onto the visual timeline."""
        name = self.anim_selector.currentText()
        if not name or name not in self.saved_animations:
            return

        self.clear_visual_timeline()
        sequence = self.saved_animations[name]

        for step in sequence:
            pose_name = step.get("pose")
            duration = step.get("duration", 2.0)
            
            if pose_name is None:
                if self.timeline_widgets and isinstance(self.timeline_widgets[-1], TimeConnectorWidget):
                    self.timeline_widgets[-1].time_input.setValue(duration)
                continue

            thumb_path = os.path.join(self.pose_icons_dir, f"{pose_name}.png")
            
            if not self.timeline_widgets:
                conn_start = TimeConnectorWidget(arrow_text="▶")
                conn_start.time_input.setValue(duration)
                self.tl_layout.addWidget(conn_start)
                self.timeline_widgets.append(conn_start)

                step_w = PoseWidget(pose_name, thumb_path, show_delete=True)
                step_w.btn_del.clicked.connect(lambda checked=False, sw=step_w: self.remove_from_timeline(sw))
                self.tl_layout.addWidget(step_w)
                self.timeline_widgets.append(step_w)

                conn_end = TimeConnectorWidget(arrow_text="↺")
                self.tl_layout.addWidget(conn_end)
                self.timeline_widgets.append(conn_end)
            else:
                conn_new = TimeConnectorWidget(arrow_text="→")
                conn_new.time_input.setValue(duration)
                step_w = PoseWidget(pose_name, thumb_path, show_delete=True)
                step_w.btn_del.clicked.connect(lambda checked=False, sw=step_w: self.remove_from_timeline(sw))

                conn_end = self.timeline_widgets.pop()
                self.tl_layout.removeWidget(conn_end)

                self.tl_layout.addWidget(conn_new)
                self.timeline_widgets.append(conn_new)

                self.tl_layout.addWidget(step_w)
                self.timeline_widgets.append(step_w)

                self.tl_layout.addWidget(conn_end)
                self.timeline_widgets.append(conn_end)

    def delete_animation(self):
        """Delete the currently selected animation from disk and selector."""
        name = self.anim_selector.currentText()
        if name and name in self.saved_animations:
            del self.saved_animations[name]
            with open(self.animations_file, "w") as f:
                json.dump(self.saved_animations, f, indent=4)
            self._refresh_anim_selector()

    # ------------------------------------------------------------------
    # Interpolation playback
    # ------------------------------------------------------------------

    def stop_playback(self):
        """Stop the currently running animation sequence."""
        self.interp_timer.stop()
        self.btn_play_seq.setText("▶ REPRODUCIR SECUENCIA")
        self.btn_play_seq.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")

    def play_sequence(self):
        """Convert the current timeline into an interpolation sequence and start playback."""
        if self.interp_timer.isActive():
            self.stop_playback()
            return

        self.current_interp_sequence = []

        for i, w in enumerate(self.timeline_widgets):
            if isinstance(w, PoseWidget):
                duration = self.timeline_widgets[i - 1].time_input.value()
                if w.pose_name in self.saved_poses:
                    self.current_interp_sequence.append(
                        {"angles": self.saved_poses[w.pose_name], "duration": duration}
                    )
                    
        if self.timeline_widgets and isinstance(self.timeline_widgets[-1], TimeConnectorWidget):
            self.loop_duration = self.timeline_widgets[-1].time_input.value()
        else:
            self.loop_duration = 0.5

        if self.current_interp_sequence:
            self.current_seq_index = 0
            self.playback_direction = 1
            self.btn_play_seq.setText("⏹ DETENER SECUENCIA")
            self.btn_play_seq.setStyleSheet("background-color: #F44336; color: white; font-weight: bold; padding: 5px;")
            self.start_next_in_sequence()

    def start_next_in_sequence(self):
        """Kick off interpolation for the next step in the sequence based on playback mode."""
        mode = self.playback_mode.currentText() if hasattr(self, 'playback_mode') else "Una Vez"

        if self.playback_direction == 1 and self.current_seq_index >= len(self.current_interp_sequence):
            if mode == "Bucle":
                self.current_seq_index = 0
                self._next_duration_override = self.loop_duration
            elif mode == "Ping-Pong":
                if len(self.current_interp_sequence) > 1:
                    self.playback_direction = -1
                    self.current_seq_index = len(self.current_interp_sequence) - 2
                    self._next_duration_override = self.loop_duration
                else:
                    self.stop_playback()
                    return
            else:
                self.stop_playback()
                return
        elif self.playback_direction == -1 and self.current_seq_index < 0:
            if mode == "Ping-Pong":
                if len(self.current_interp_sequence) > 1:
                    self.playback_direction = 1
                    self.current_seq_index = 1
                    self._next_duration_override = self.loop_duration
                else:
                    self.stop_playback()
                    return
            else:
                self.stop_playback()
                return

        target = self.current_interp_sequence[self.current_seq_index]
        self.target_angles = target["angles"]
        
        duration = getattr(self, "_next_duration_override", None)
        if duration is None:
            if self.playback_direction == -1 and self.current_seq_index + 1 < len(self.current_interp_sequence):
                duration = self.current_interp_sequence[self.current_seq_index + 1]["duration"]
            else:
                duration = target["duration"]
                
        self._next_duration_override = None

        duration = max(duration, 0.05)  # Minimum 50 ms to avoid div-by-zero

        fps = 30
        self.interp_steps = max(1, int(duration * fps))
        self.interp_count = 0

        self.current_angles_f = [float(s.value()) for s in self.sliders]
        
        # Asegurar que target_angles tiene suficientes elementos (compat. poses con 3 ángulos)
        while len(self.target_angles) < len(self.sliders):
            self.target_angles.append(0)
        
        self.interp_deltas = [
            (self.target_angles[i] - self.current_angles_f[i]) / self.interp_steps
            for i in range(len(self.sliders))
        ]

        self.interp_timer.start(int(1000 / fps))

    def update_interpolation(self):
        """Called by interp_timer on each tick to advance the current interpolation step."""
        self.interp_count += 1
        if self.interp_count <= self.interp_steps:
            for i in range(len(self.sliders)):
                self.current_angles_f[i] += self.interp_deltas[i]
                self.sliders[i].blockSignals(True)
                self.sliders[i].setValue(int(round(self.current_angles_f[i])))
                self.sliders[i].blockSignals(False)
            self.send_angles()
        else:
            self.interp_timer.stop()
            # Snap to exact target values (eliminate float accumulation error)
            for i in range(len(self.sliders)):
                if i < len(self.target_angles):
                    self.sliders[i].blockSignals(True)
                    self.sliders[i].setValue(self.target_angles[i])
                    self.sliders[i].blockSignals(False)
            self.send_angles()

            self.current_seq_index += self.playback_direction
            self.start_next_in_sequence()
