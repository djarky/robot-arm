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
        """Connect or disconnect the Arduino serial port."""
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
