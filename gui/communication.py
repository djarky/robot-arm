"""
gui/communication.py — Mixin providing UDP, Serial, and config I/O.

Classes:
    CommunicationMixin — Methods for sending/receiving angle data via UDP socket,
                         managing serial (Arduino) connection, and persisting session config.
                         Designed to be mixed into RobotGui (QMainWindow subclass).
"""
import json
import serial
import serial.tools.list_ports
import sys
import os
import time
import subprocess
from PySide6.QtCore import QTimer


class CommunicationMixin:
    """Mixin that adds UDP + Serial communication and config persistence.

    Expects the host class to provide:
        self.sock              (socket.socket) — outgoing UDP socket
        self.recv_sock         (socket.socket) — incoming UDP socket
        self.target_addr       (tuple)         — (host, port) for simulation
        self.ser               (serial.Serial) — Arduino serial connection (or None)
        self.sliders           (list)          — joint slider widgets
        self.port_selector     (QComboBox)     — serial port dropdown
        self.btn_refresh       (QPushButton)   — refresh ports button
        self.btn_connect       (QPushButton)   — connect/disconnect button
        self.conn_status       (QLabel)        — connection status label
        self.sock              (socket.socket) — UDP send socket
        self.obj_type          (QComboBox)     — spawn object type
        self.obj_size          (QDoubleSpinBox)
        self.obj_mass          (QDoubleSpinBox)
    """

    # ------------------------------------------------------------------
    # Angle transmission
    # ------------------------------------------------------------------

    def send_angles(self):
        """Send slider angles to both the 3-D simulation (UDP) and Arduino (Serial)."""
        angles = [s.value() for s in self.sliders]
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.target_addr)

        if self.ser and self.ser.is_open:
            # Format: "ANG0,ANG1,ANG2,ANG3,ANG4,GRIPPER\n" (offset by +90 to map -90..90 → 0..180)
            parts = [str(a + 90) for a in angles]
            serial_msg = ",".join(parts) + ",0\n"
            self.ser.write(serial_msg.encode())

    def send_camera_angles(self, angles: list):
        """Send angles derived from camera tracking to the simulation."""
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.target_addr)

    def spawn_request(self):
        """Send a spawn request for an object to the simulation."""
        msg = json.dumps({
            "type": "spawn",
            "shape": self.obj_type.currentText(),
            "size": self.obj_size.value(),
            "mass": self.obj_mass.value(),
        })
        self.sock.sendto(msg.encode(), self.target_addr)

    def reset_camera_sim(self):
        """Tell the simulation to reset its camera view."""
        msg = json.dumps({"type": "reset_camera"})
        self.sock.sendto(msg.encode(), self.target_addr)

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
    # UDP feedback from simulation
    # ------------------------------------------------------------------

    def sync_from_sim(self):
        """Poll the receive socket and sync slider values from simulation feedback."""
        try:
            while True:
                data, _ = self.recv_sock.recvfrom(4096)
                msg = json.loads(data.decode())
                if msg.get("type") == "sync_angles":
                    angles = msg["data"]
                    for i, angle in enumerate(angles):
                        if i < len(self.sliders):
                            self.sliders[i].blockSignals(True)
                            self.sliders[i].setValue(int(angle))
                            self.sliders[i].blockSignals(False)
                elif msg.get("type") == "path_result":
                    # Sim has computed a collision-safe path
                    waypoints = msg.get("waypoints", [])
                    duration = msg.get("duration", 1.0)
                    evasion = msg.get("evasion", False)
                    if evasion:
                        print(f"[Collision] Evasion path with {len(waypoints)} waypoints")
                    self._execute_safe_path(waypoints, duration, evasion)
                elif msg.get("type") == "collision_status":
                    self._update_collision_indicator(msg)
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"Error en sync_from_sim: {e}")

    # ------------------------------------------------------------------
    # Serial (Arduino) management
    # ------------------------------------------------------------------

    def refresh_ports(self):
        """Populate the port selector combo with available serial ports, filtered for Arduino."""
        self.port_selector.clear()
        all_ports = serial.tools.list_ports.comports()
        
        # Filter for typical Arduino names:
        # Linux: ttyUSB* or ttyACM*
        # Windows: COM*
        if sys.platform == "win32":
            filtered_ports = [p for p in all_ports if "COM" in p.device.upper()]
        else:
            filtered_ports = [p for p in all_ports if "ttyUSB" in p.device or "ttyACM" in p.device]
        
        for port in filtered_ports:
            self.port_selector.addItem(port.device)

        if not filtered_ports:
            self.conn_status.setText("No compatible ports found")
        else:
            self.conn_status.setText(f"Found {len(filtered_ports)} compatible ports")

    def toggle_serial(self):
        """Connect or disconnect the Arduino serial port with verification."""
        if self.ser is None or not self.ser.is_open:
            selected_port = self.port_selector.currentText()
            if not selected_port:
                self.set_conn_status("Error: No port selected", "error")
                return
            try:
                # Open port
                self.ser = serial.Serial(selected_port, 115200, timeout=0.1)
                
                # IMPORTANT: Many Arduinos reset when the serial port is opened.
                # We need to wait for it to boot up before sending the handshake.
                time.sleep(2.0)
                
                # Handshake verification
                if self.verify_arduino():
                    self.set_conn_status(f"Connected: {selected_port}", "success")
                    self.btn_connect.setText("Disconnect")
                    self.port_selector.setEnabled(False)
                    self.btn_refresh.setEnabled(False)
                    # Start monitoring serial responses if not already started
                    if not hasattr(self, 'serial_timer'):
                        self.serial_timer = QTimer()
                        self.serial_timer.timeout.connect(self.read_serial_feedback)
                    self.serial_timer.start(50)
                else:
                    self.ser.close()
                    self.ser = None
                    self.set_conn_status("Error: Sketch unrecognized", "error")
                    
            except serial.SerialException as e:
                self.ser = None
                if "Device or resource busy" in str(e) or "Access is denied" in str(e):
                    self.set_conn_status("Error: Port busy", "error")
                else:
                    self.set_conn_status(f"Error: {str(e)}", "error")
            except Exception as e:
                self.ser = None
                self.set_conn_status(f"Error: {str(e)}", "error")
        else:
            if hasattr(self, 'serial_timer'):
                self.serial_timer.stop()
            self.ser.close()
            self.ser = None
            self.set_conn_status("Status: Disconnected", "normal")
            self.btn_connect.setText("Connect Arduino")
            self.port_selector.setEnabled(True)
            self.btn_refresh.setEnabled(True)

    def verify_arduino(self):
        """Sends identification command and waits for response."""
        if not self.ser or not self.ser.is_open:
            return False
        
        # Clear buffers
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        
        # Send query
        self.ser.write(b"?\n")
        
        # Wait for response (up to 2 seconds)
        start_time = time.time()
        while (time.time() - start_time) < 2.0:
            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode().strip()
                if line == "ID:ARM_ROBOT":
                    return True
            time.sleep(0.1)
        return False

    def read_serial_feedback(self):
        """Reads ACK/ERROR from Arduino to verify packet reception."""
        if self.ser and self.ser.is_open:
            try:
                while self.ser.in_waiting > 0:
                    line = self.ser.readline().decode().strip()
                    if line == "ACK":
                        # notify success (we can add a counter or flash a led)
                        if hasattr(self, 'on_packet_received'):
                            self.on_packet_received(True)
                    elif line.startswith("ERROR"):
                        if hasattr(self, 'on_packet_received'):
                            self.on_packet_received(False, line)
            except Exception as e:
                print(f"Serial feedback error: {e}")

    def set_conn_status(self, text, type="normal"):
        """Helper to style the status label."""
        self.conn_status.setText(text)
        styles = {
            "normal": "color: #ccc;",
            "success": "color: #4CAF50; font-weight: bold;",
            "error": "color: #f44336; font-weight: bold;"
        }
        self.conn_status.setStyleSheet(styles.get(type, styles["normal"]))

    # ------------------------------------------------------------------
    # Session config persistence
    # ------------------------------------------------------------------

    def load_config(self):
        """Restore joint angles and serial port from config.json."""
        import os
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)

                angles = config.get("joint_angles", [0, 0, 0, 0, 0, 0])
                # Padding para configs antiguas con menos de 5 ángulos
                while len(angles) < len(self.sliders):
                    angles.append(0)
                for i, angle in enumerate(angles):
                    if i < len(self.sliders):
                        self.sliders[i].setValue(angle)

                last_port = config.get("serial_port")
                if last_port:
                    index = self.port_selector.findText(last_port)
                    if index >= 0:
                        self.port_selector.setCurrentIndex(index)
        except Exception as e:
            print(f"Error loading config: {e}")

    def save_config(self):
        """Persist joint angles and serial port selection to config.json."""
        import os
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

    # ------------------------------------------------------------------
    # Collision-aware path execution
    # ------------------------------------------------------------------

    def _execute_safe_path(self, waypoints, original_duration, evasion_needed):
        """Execute waypoints returned by the sim's collision interpolator.

        If evasion was needed, the waypoints list has 3 entries
        (lift, transit, lower) and we split the original duration
        across them (half-speed per sub-phase).

        This method converts the waypoints into the existing
        interpolation machinery used by AnimationManagerMixin.
        """
        if not waypoints:
            return

        if evasion_needed and len(waypoints) > 1:
            # Distribute time: each sub-phase gets duration / num_waypoints
            sub_duration = original_duration / len(waypoints)
            # Build an expanded sequence and play it
            self._pending_safe_waypoints = []
            for wp in waypoints:
                self._pending_safe_waypoints.append({
                    "angles": wp,
                    "duration": sub_duration
                })
        else:
            self._pending_safe_waypoints = [{
                "angles": waypoints[0],
                "duration": original_duration
            }]

        # Start playing the first waypoint
        self._safe_wp_index = 0
        self._play_next_safe_waypoint()

    def _play_next_safe_waypoint(self):
        """Play one waypoint from the safe path, then advance."""
        if not hasattr(self, '_pending_safe_waypoints'):
            return
        if self._safe_wp_index >= len(self._pending_safe_waypoints):
            # Done with safe path — continue the main animation sequence
            del self._pending_safe_waypoints
            del self._safe_wp_index
            # Advance the main sequence
            if hasattr(self, 'current_seq_index') and hasattr(self, 'playback_direction'):
                self.current_seq_index += self.playback_direction
                self.start_next_in_sequence()
            return

        wp = self._pending_safe_waypoints[self._safe_wp_index]
        self.target_angles = wp["angles"]
        duration = max(wp["duration"], 0.05)

        fps = 30
        self.interp_steps = max(1, int(duration * fps))
        self.interp_count = 0

        self.current_angles_f = [float(s.value()) for s in self.sliders]

        # Pad target if necessary
        while len(self.target_angles) < len(self.sliders):
            self.target_angles.append(0)

        self.interp_deltas = [
            (self.target_angles[i] - self.current_angles_f[i]) / self.interp_steps
            for i in range(len(self.sliders))
        ]

        # Override the completion callback so it chains to the next waypoint
        self._safe_path_active = True
        self._safe_wp_index += 1
        self.interp_timer.start(int(1000 / fps))

    def _update_collision_indicator(self, msg):
        """Update the collision LED indicator in the GUI."""
        if not hasattr(self, 'collision_indicator'):
            return
        colliding = msg.get("colliding", False)
        joints = msg.get("joints", [])
        if colliding:
            self.collision_indicator.setText("● COLISIÓN")
            self.collision_indicator.setStyleSheet(
                "color: #f44336; font-size: 14px; font-weight: bold;"
            )
            self.collision_indicator.setToolTip(f"Probes: {', '.join(joints)}")
        else:
            self.collision_indicator.setText("● OK")
            self.collision_indicator.setStyleSheet(
                "color: #4CAF50; font-size: 14px; font-weight: bold;"
            )
            self.collision_indicator.setToolTip("Sin colisión")
