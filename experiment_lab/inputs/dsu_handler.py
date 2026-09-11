import socket
import struct
import threading
import time

from .base import BaseInputHandler

# Packet signature to request data from DSU server (Cemuhook protocol)
DSU_REQUEST_PACKET = b"DSUC\351\003\f\000\016\363\371\333\000\000\000\000\002\000\020\000\001\000\000\000\000\000\000\000"

class DSUClient:
    """Implementación del protocolo DSU (Cemuhook) como cliente (polling)."""

    def __init__(self, host='127.0.0.1', port=26760):
        self.host = host
        self.port = port
        self.active = False
        self.data = {
            "accel": [0.0, 0.0, 0.0],
            "gyro": [0.0, 0.0, 0.0],
            "sticks": {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            "buttons": {}
        }
        self.sock = None
        self._listen_thread = None
        self._poll_thread = None

    def start(self):
        if self.active:
            return
        self.active = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # En modo cliente no hacemos bind a un puerto fijo local necesariamente,
            # pero establecemos el timeout para recvfrom.
            self.sock.settimeout(1.0)
            
            self._listen_thread = threading.Thread(target=self._listen, daemon=True)
            self._listen_thread.start()
            
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            
            print(f"[Input/DSU] Polling {self.host}:{self.port}")
        except Exception as e:
            print(f"[Input/DSU] Error initializing DSU client: {e}")
            self.active = False

    def _poll_loop(self):
        """Envía el paquete de suscripción periódicamente."""
        while self.active:
            try:
                if self.sock:
                    self.sock.sendto(DSU_REQUEST_PACKET, (self.host, self.port))
            except Exception:
                pass
            time.sleep(1.0)

    def _listen(self):
        while self.active:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) < 20:
                    continue
                
                # Header: Magic(4), Version(2), Len(2), CRC(4), ServerID(4), MsgType(4)
                msg_type = struct.unpack("<I", data[16:20])[0]
                
                if msg_type == 0x100002:  # Data message
                    if len(data) < 100:
                        continue
                        
                    # 20: PadID(1), State(1), Model(1), Conn(1), MAC(6), Battery(1), Active(1), PacketCounter(4)
                    # 36: Digital1(1), Digital2(1), Home(1), Touch(1)
                    # 40: LX(1), LY(1), RX(1), RY(1)
                    # 44: DpadL, DpadD, DpadR, DpadU, Square, Cross, Circle, Triangle, R1, L1, R2, L2 (todo en 1 byte cada uno si es analógico o digital?)
                    
                    # Siguiendo estructura de Universal-Remote/udp_listener.py
                    # 40: LX, LY, RX, RY
                    lx, ly, rx, ry = struct.unpack("BBBB", data[40:44])
                    self.data["sticks"]["lx"] = (lx - 128) / 128.0
                    self.data["sticks"]["ly"] = (ly - 128) / 128.0
                    self.data["sticks"]["rx"] = (rx - 128) / 128.0
                    self.data["sticks"]["ry"] = (ry - 128) / 128.0
                    
                    # Botones (Offsets aproximados basados en el struct del addon)
                    # El addon usa campos individuales. Vamos a mapear los más importantes.
                    # 36: buttons1 (Digital 1)
                    # 37: buttons2 (Digital 2)
                    b1 = data[36]
                    b2 = data[37]
                    
                    # Mapear a códigos internos (pueden ser arbitrarios pero consistentes)
                    # Digital 1: Share, L3, R3, Options, Up, Right, Down, Left
                    # Digital 2: L2, R2, L1, R1, Triangle, Circle, Cross, Square
                    self.data["buttons"] = {
                        0: (b2 >> 0) & 1,  # Square / Cross? Depende del servidor
                        1: (b2 >> 1) & 1,  # Cross
                        2: (b2 >> 2) & 1,  # Circle
                        3: (b2 >> 3) & 1,  # Triangle
                        4: (b2 >> 4) & 1,  # L1
                        5: (b2 >> 5) & 1,  # R1
                        6: (b2 >> 6) & 1,  # L2 (Digital)
                        7: (b2 >> 7) & 1,  # R2 (Digital)
                        8: (b1 >> 0) & 1,  # Share
                        9: (b1 >> 3) & 1,  # Options
                    }
                    
                    # Sensores de movimiento (Offsets correctos con cabecera de 20 bytes incluida):
                    # Accel X, Y, Z (Floats en g's - Payload offset 56 -> UDP offset 76)
                    accel_x, accel_y, accel_z = struct.unpack("<fff", data[76:88])
                    self.data["accel"] = [accel_x, accel_y, accel_z]
                    
                    # Gyro Pitch, Yaw, Roll (Floats en deg/s - Payload offset 68 -> UDP offset 88)
                    gyro_p, gyro_y, gyro_r = struct.unpack("<fff", data[88:100])
                    self.data["gyro"] = [gyro_p, gyro_y, gyro_r]

            except socket.timeout:
                continue
            except Exception:
                break

    def stop(self):
        self.active = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None


class DSUHandler(BaseInputHandler):
    """Handler para entrada vía protocolo DSU/Cemuhook (UDP Client)."""

    def __init__(self):
        self.client = DSUClient()

    def activate(self, device_id=None, **kwargs):
        """Inicia el cliente DSU con la IP y puerto especificados."""
        host = kwargs.get("host", "127.0.0.1")
        port = kwargs.get("port", 26760)
        
        # Si ya está activo con la misma config, no reiniciar
        if self.client.active and self.client.host == host and self.client.port == port:
            return
            
        self.client.stop()
        self.client.host = host
        self.client.port = port
        self.client.start()

    def deactivate(self):
        """Detiene el cliente DSU."""
        self.client.stop()

    def poll(self):
        """El cliente corre en hilos separados, no requiere polling manual aquí."""
        pass

    def get_direct_inputs(self):
        """
        Mapeo directo heredado (acelerómetros).
        Para usar botones/sticks del DSU, se debería usar el sistema de binds.
        """
        if not self.client.active:
            return None

        accel = self.client.data["accel"]
        # Mapeo crudo: X -> Base, Y -> Hombro
        joy_inputs = [accel[0], accel[1], 0.0, 0.0, 0.0, 0.0, 0.0]

        return joy_inputs, {}, [0.0] * 7

    def get_last_input(self):
        """
        Detecta sticks, botones, giroscopio o acelerómetro para el mapper
        seleccionando el eje de mayor intensidad y filtrando la gravedad.
        """
        if not self.client.active:
            return None

        # 1. Detectar Botones de manera inmediata ya que son discretos y explícitos
        for bid, val in self.client.data["buttons"].items():
            if val:
                return ("button", bid)

        # 2. Detectar Eje con mayor intensidad para evitar solapamientos y descartar la gravedad
        best_input = None
        max_val = 0.0

        # Sticks analógicos (lx, ly, rx, ry)
        for sid, val in self.client.data["sticks"].items():
            abs_val = abs(val)
            if abs_val > max_val and abs_val > 0.5:
                max_val = abs_val
                best_input = ("axis", sid)

        # Acelerómetros (accel_0, accel_1, accel_2)
        # La gravedad constante es ~1.0G. Requerimos >1.5G (movimiento brusco o sacudida rápida) para bindear.
        for i, val in enumerate(self.client.data["accel"]):
            abs_val = abs(val)
            if abs_val > max_val and abs_val > 1.5:
                max_val = abs_val
                best_input = ("axis", f"accel_{i}")

        # Giroscopios (gyro_0, gyro_1, gyro_2)
        # Giroscopios reportan deg/s. Dividimos por 200.0 para escala normalizada.
        # Un giro deliberado supera 0.6 fácilmente (~120 deg/s).
        for i, val in enumerate(self.client.data["gyro"]):
            scaled_val = abs(val / 200.0)
            if scaled_val > max_val and scaled_val > 0.6:
                max_val = scaled_val
                best_input = ("axis", f"gyro_{i}")

        return best_input

    def read_bind(self, bind, deadzone=0.1):
        """Resuelve un bind usando el estado del cliente DSU."""
        if not self.client.active:
            return 0.0

        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "button":
            return 1.0 if self.client.data["buttons"].get(iid, 0) else 0.0

        if itype == "axis":
            val = 0.0
            if iid in self.client.data["sticks"]:
                val = self.client.data["sticks"][iid]
            elif str(iid).startswith("accel_"):
                idx = int(iid.split("_")[1])
                val = self.client.data["accel"][idx]
            elif str(iid).startswith("gyro_"):
                idx = int(iid.split("_")[1])
                # Escalar los valores del giroscopio (grados/s) para que estén en un rango útil (-1.0 a 1.0).
                # Dividir por 200.0 es un estándar común para control de movimiento en juegos.
                val = self.client.data["gyro"][idx] / 200.0
            
            if abs(val) < deadzone:
                return 0.0
            return val

        return 0.0

    def get_friendly_bind_name(self, bind):
        """Retorna un nombre amigable en español para los botones y ejes del control DSU."""
        if not bind:
            return "SIN ASIGNAR"
        itype = bind.get("type")
        iid = bind.get("id")
        
        if itype == "button":
            button_names = {
                0: "Botón Cuadrado / Y",
                1: "Botón Cruz / A",
                2: "Botón Círculo / B",
                3: "Botón Triángulo / X",
                4: "Botón L1",
                5: "Botón R1",
                6: "Gatillo L2 (Digital)",
                7: "Gatillo R2 (Digital)",
                8: "Botón Share / Select",
                9: "Botón Options / Start",
            }
            return button_names.get(iid, f"Botón {iid}")
            
        elif itype == "axis":
            axis_names = {
                "lx": "Stick Izquierdo X",
                "ly": "Stick Izquierdo Y",
                "rx": "Stick Derecho X",
                "ry": "Stick Derecho Y",
                "accel_0": "Inclinación X (Lateral)",
                "accel_1": "Inclinación Y (Frontal)",
                "accel_2": "Inclinación Z (Elevación)",
                "gyro_0": "Giro Pitch (Cabeceo)",
                "gyro_1": "Giro Yaw (Giro)",
                "gyro_2": "Giro Roll (Alabeo)",
            }
            return axis_names.get(iid, f"Eje {iid}")
            
        return f"{itype.capitalize()} {iid}"

    def flush(self):
        """No hay cola de eventos que vaciar, usamos estado instantáneo."""
        pass
