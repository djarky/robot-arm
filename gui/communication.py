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
import time
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
            # Format: "ANG1,ANG2,ANG3,GRIPPER\n" (offset by +90 to map -90..90 → 0..180)
            serial_msg = f"{angles[0] + 90},{angles[1] + 90},{angles[2] + 90},0\n"
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

    # ------------------------------------------------------------------
    # UDP feedback from simulation
    # ------------------------------------------------------------------

    def sync_from_sim(self):
        """Poll the receive socket and sync slider values from simulation feedback."""
        try:
            while True:
                data, _ = self.recv_sock.recvfrom(1024)
                msg = json.loads(data.decode())
                if msg.get("type") == "sync_angles":
                    angles = msg["data"]
                    for i, angle in enumerate(angles):
                        if i < len(self.sliders):
                            self.sliders[i].blockSignals(True)
                            self.sliders[i].setValue(int(angle))
                            self.sliders[i].blockSignals(False)
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

                angles = config.get("joint_angles", [0, 0, 0])
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
