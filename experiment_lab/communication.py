import socket
import json
import serial
import serial.tools.list_ports
import time
import sys

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

class LabCommunication:
    """
    Gestiona la comunicación UDP con Ursina, Serial con Arduino y WiFi vía MQTT.
    """
    def __init__(self, sim_ip="127.0.0.1", sim_port=5005, feedback_port=5006):
        self.sim_addr = (sim_ip, sim_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.recv_sock.bind(("127.0.0.1", feedback_port))
            self.recv_sock.setblocking(False)
        except Exception as e:
            print(f"[Comm] Error bind feedback socket: {e}")

        self.ser = None
        
        # MQTT Attributes
        self.mqtt_client = None
        self.mqtt_connected = False
        self.mqtt_broker = ""
        self.mqtt_port = 1883
        self.mqtt_topic = ""

    def connect_mqtt(self, broker, port, topic):
        """Inicializa y conecta el cliente MQTT de forma no bloqueante."""
        if not MQTT_AVAILABLE:
            print("[Comm] ERROR: paho-mqtt no está instalado en el entorno.")
            return False
            
        try:
            if self.mqtt_connected:
                self.disconnect_mqtt()
                
            self.mqtt_broker = broker
            self.mqtt_port = port
            self.mqtt_topic = topic
            
            try:
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except AttributeError:
                # Fallback para versiones antiguas de paho-mqtt
                self.mqtt_client = mqtt.Client()
                
            self.mqtt_client.connect(broker, port, keepalive=60)
            self.mqtt_client.loop_start()
            self.mqtt_connected = True
            return True
        except Exception as e:
            print(f"[Comm] Error al conectar a MQTT: {e}")
            self.mqtt_client = None
            self.mqtt_connected = False
            return False

    def disconnect_mqtt(self):
        """Detiene el loop de red de MQTT y se desconecta de forma limpia."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                print(f"[Comm] Error al desconectar MQTT: {e}")
            self.mqtt_client = None
        self.mqtt_connected = False

    def send_angles(self, angles):
        """Envía ángulos a la simulación, al Arduino y por MQTT si está activo."""
        # Ursina (UDP)
        msg = json.dumps({"type": "angles", "data": angles})
        self.sock.sendto(msg.encode(), self.sim_addr)

        # Arduino (Serial)
        if self.ser and self.ser.is_open:
            parts = [str(int(a + 90)) for a in angles]
            serial_msg = ",".join(parts) + ",0\n"
            try:
                self.ser.write(serial_msg.encode())
            except Exception as e:
                print(f"[Comm] Serial write error: {e}")

        # MQTT (WiFi)
        if self.mqtt_connected and self.mqtt_client:
            parts = [str(int(a + 90)) for a in angles]
            mqtt_msg = ",".join(parts) + ",0"
            try:
                self.mqtt_client.publish(self.mqtt_topic, mqtt_msg)
            except Exception as e:
                print(f"[Comm] Error al publicar MQTT: {e}")

    def send_camera_offsets(self, offsets):
        """Envía los deltas de cámara a la simulación."""
        msg = json.dumps({"type": "camera_offset", "data": offsets})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def request_screenshot(self, path):
        """Solicita a la simulación que guarde una captura en el path indicado."""
        msg = json.dumps({"type": "screenshot", "path": path})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def spawn_object(self, obj_type, size, mass, model_path=None):
        """Envía una solicitud para spawnear un objeto en la simulación."""
        msg_dict = {
            "type": "spawn",
            "shape": obj_type,
            "size": size,
            "mass": mass,
        }
        if model_path:
            msg_dict["model_path"] = model_path
            
        msg = json.dumps(msg_dict)
        self.sock.sendto(msg.encode(), self.sim_addr)

    def load_svg(self, path):
        """Envía la ruta de un archivo SVG a la simulación para crear el blueprint."""
        msg = json.dumps({"type": "load_svg", "path": path})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def start_svg_trajectory(self):
        """Inicia la ejecución de la trayectoria cargada."""
        msg = json.dumps({"type": "start_svg_trajectory"})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def stop_svg_trajectory(self):
        """Detiene la ejecución de la trayectoria inmediatamente."""
        msg = json.dumps({"type": "stop_svg_trajectory"})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def reset_cnc_trace(self):
        """Solicita a la simulación que limpie el rastro visual del dibujo."""
        msg = json.dumps({"type": "reset_cnc"})
        self.sock.sendto(msg.encode(), self.sim_addr)

    def set_cnc_params(self, safety_height, feedrate):
        """Envía parámetros de configuración CNC a la simulación."""
        msg = json.dumps({"type": "set_cnc_params", "safety_height": safety_height, "feedrate": feedrate})
        self.sock.sendto(msg.encode(), self.sim_addr)


    def connect_arduino(self, port, baud=115200):
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            
            # Use 3s timeout to allow Arduino setup() scan to finish
            print(f"[Comm] Esperando inicialización de Arduino en {port}...")
            time.sleep(3.0)
            
            self.ser.reset_input_buffer()
            print(f"[Comm] Arduino conectado en {port}")
            return True
        except serial.SerialException as e:
            err = str(e)
            if "Permission denied" in err or "[Errno 13]" in err:
                print(f"[Comm] ERROR PERMISOS: Usuario no está en grupo 'dialout'.")
                print("       Ejecute: sudo usermod -aG dialout $USER y REINICIE SESION.")
            else:
                print(f"[Comm] Error serial: {e}")
            return False
        except Exception as e:
            print(f"[Comm] Error inesperado: {e}")
            return False

    def get_feedback(self):
        """
        Lee todos los paquetes de feedback pendientes y retorna el último.
        Esto evita latencia acumulada en el buffer UDP.
        """
        last_msg = None
        while True:
            try:
                data, _ = self.recv_sock.recvfrom(4096)
                last_msg = json.loads(data.decode())
            except (BlockingIOError, socket.error):
                break
            except Exception as e:
                print(f"[Comm] Feedback error: {e}")
                break
        return last_msg

    @staticmethod
    def list_ports(filter_arduino=True):
        all_ports = serial.tools.list_ports.comports()
        if not filter_arduino:
            return [p.device for p in all_ports]
            
        # Filtro similar a la GUI principal
        if sys.platform == "win32":
            return [p.device for p in all_ports if "COM" in p.device.upper()]
        else:
            return [p.device for p in all_ports if "ttyUSB" in p.device or "ttyACM" in p.device]
