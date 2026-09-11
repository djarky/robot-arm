"""
wiimote_handler.py — Handler especializado para Nintendo Wiimote.

Lógica completamente aislada del resto del sistema:
  - Conexión vía múltiples nodos evdev (Botones, Acelerómetros, IR).
  - Emparejamiento Bluetooth vía bluetoothctl.
  - Lectura directa de acelerómetros (no pasa por el sistema de binds).
"""

import time
import threading
import subprocess

from .base import BaseInputHandler

try:
    import evdev
    from evdev import ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False


class WiimoteHandler(BaseInputHandler):
    """Handler para Nintendo Wiimote vía evdev multi-nodo + bluetoothctl."""

    def __init__(self):
        self.nodes = {}           # Diccionario {tag: evdev.InputDevice}
        self.active = False
        self.is_pairing = False
        self.state = {
            "accel": [0.0, 0.0, 0.0],
            "gyro": [0.0, 0.0, 0.0],
            "nunchuk_accel": [0.0, 0.0, 0.0],
            "nunchuk_axes": {},
            "buttons": {}
        }

    def activate(self, device_id=None, **kwargs):
        """Busca y conecta los nodos del Wiimote."""
        self.connect_wiimote()

    def deactivate(self):
        """Cierra todos los nodos del Wiimote."""
        for tag, dev in self.nodes.items():
            try:
                dev.close()
            except Exception:
                pass
        self.nodes = {}
        self.active = False
        self.state = {
            "accel": [0.0, 0.0, 0.0],
            "gyro": [0.0, 0.0, 0.0],
            "nunchuk_accel": [0.0, 0.0, 0.0],
            "nunchuk_axes": {},
            "buttons": {}
        }

    def poll(self):
        """Lee eventos de todos los nodos vinculados al Wiimote (Botones + Accel + Nunchuk)."""
        if not self.active or not self.nodes:
            return

        import select
        # Verificar qué nodos tienen datos disponibles (non-blocking)
        devs_list = list(self.nodes.values())
        readable, _, _ = select.select(devs_list, [], [], 0)

        for dev in readable:
            # Encontrar el tag de este dispositivo
            tag = None
            for t, d in self.nodes.items():
                if d == dev:
                    tag = t
                    break
            if not tag:
                continue

            try:
                while True:
                    event = dev.read_one()
                    if event is None:
                        break
                    if event.type == ecodes.EV_ABS:
                        if tag == "accel":
                            if event.code == ecodes.ABS_RX:
                                self.state["accel"][0] = event.value / 500.0
                            elif event.code == ecodes.ABS_RY:
                                self.state["accel"][1] = event.value / 500.0
                            elif event.code == ecodes.ABS_RZ:
                                self.state["accel"][2] = event.value / 500.0
                        elif tag == "gyro":
                            if event.code == ecodes.ABS_RX:
                                self.state["gyro"][0] = event.value / 16000.0
                            elif event.code == ecodes.ABS_RY:
                                self.state["gyro"][1] = event.value / 16000.0
                            elif event.code == ecodes.ABS_RZ:
                                self.state["gyro"][2] = event.value / 16000.0
                        elif tag == "nunchuk_accel":
                            if event.code == ecodes.ABS_RX:
                                self.state["nunchuk_accel"][0] = event.value / 500.0
                            elif event.code == ecodes.ABS_RY:
                                self.state["nunchuk_accel"][1] = event.value / 500.0
                            elif event.code == ecodes.ABS_RZ:
                                self.state["nunchuk_accel"][2] = event.value / 500.0
                        elif tag == "nunchuk":
                            # El nodo principal Nunchuk emite Joystick (HAT0X/Y) y Acelerómetro (RX/RY/RZ)
                            if event.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                                # El joystick del nunchuk suele tener min=-120, max=120
                                self.state["nunchuk_axes"][event.code] = event.value / 120.0
                            elif event.code == ecodes.ABS_RX:
                                self.state["nunchuk_accel"][0] = event.value / 500.0
                            elif event.code == ecodes.ABS_RY:
                                self.state["nunchuk_accel"][1] = event.value / 500.0
                            elif event.code == ecodes.ABS_RZ:
                                self.state["nunchuk_accel"][2] = event.value / 500.0
                            
                    elif event.type == ecodes.EV_KEY:
                        # Los botones (tanto del control remoto como del Nunchuk) comparten el mismo diccionario
                        self.state["buttons"][event.code] = event.value
            except (BlockingIOError, OSError):
                continue

    def get_direct_inputs(self):
        """Wiimote ahora usa el sistema unificado de binds (Retorna None)."""
        return None

    def get_last_input(self):
        """Detecta botones o inclinaciones (ejes virtuales) para el mapper."""
        if not self.active:
            return None

        self.poll()

        # 1. Detectar Botones presionados (desde el state que poll() actualiza)
        for code, val in self.state["buttons"].items():
            if val:
                return ("button", code)

        # 2. Detectar Eje con mayor intensidad (para evitar binds erróneos por gravedad)
        best_axis = None
        max_val = 0.0

        # Accel (Wiimote)
        for i in range(3):
            val = abs(self.state["accel"][i])
            # La gravedad constante es ~1.0G. Requerimos >1.5G (movimiento brusco) para bindear.
            if val > max_val and val > 1.5:
                max_val = val
                best_axis = ("axis", i)       # IDs 0, 1, 2 para Accel

        # Gyro (Wiimote)
        for i in range(3):
            val = abs(self.state["gyro"][i])
            # El gyro no sufre gravedad, un giro normal supera 0.6 fácilmente.
            if val > max_val and val > 0.6:
                max_val = val
                best_axis = ("axis", i + 3)   # IDs 3, 4, 5 para Gyro

        # Accel (Nunchuk)
        for i in range(3):
            val = abs(self.state["nunchuk_accel"][i])
            if val > max_val and val > 1.5:
                max_val = val
                best_axis = ("axis", i + 6)   # IDs 6, 7, 8 para Nunchuk Accel

        # Joystick (Nunchuk)
        for code, val in self.state["nunchuk_axes"].items():
            val = abs(val)
            if val > max_val and val > 0.5:
                max_val = val
                best_axis = ("axis", code + 100) # Offset para diferenciar de ejes virtuales

        return best_axis

    def read_bind(self, bind, deadzone=0.1):
        """
        Resuelve un bind usando el estado interno del Wiimote.
        
        IDs Ejes Virtuales:
            0,1,2 -> Accel X,Y,Z
            3,4,5 -> Gyro X,Y,Z
            6,7,8 -> Nunchuk Accel X,Y,Z
            > 100 -> Nunchuk Axes
        """
        if not self.active:
            return 0.0

        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "button":
            return 1.0 if self.state["buttons"].get(iid, 0) else 0.0

        if itype == "axis":
            val = 0.0
            if 0 <= iid <= 2:
                val = self.state["accel"][iid]
            elif 3 <= iid <= 5:
                val = self.state["gyro"][iid - 3]
            elif 6 <= iid <= 8:
                val = self.state["nunchuk_accel"][iid - 6]
            elif iid >= 100:
                val = self.state["nunchuk_axes"].get(iid - 100, 0.0)
            
            # Aplicar zona muerta
            if abs(val) < deadzone:
                return 0.0
            return val

        return 0.0

    def get_friendly_bind_name(self, bind):
        """Retorna un nombre amigable en español para los botones y ejes del Wiimote/Nunchuk."""
        if not bind:
            return "SIN ASIGNAR"
        itype = bind.get("type")
        iid = bind.get("id")
        
        if itype == "button":
            button_names = {
                304: "Botón A",
                305: "Botón B",
                306: "Botón C (Nunchuk)",
                309: "Botón Z (Nunchuk)",
                412: "Botón -",
                407: "Botón +",
                257: "Botón 1",
                258: "Botón 2",
                103: "Botón D-Pad UP",
                108: "Botón D-Pad DOWN",
                105: "Botón D-Pad LEFT",
                106: "Botón D-Pad RIGHT",
                316: "Botón Casa (Home)"
            }
            return button_names.get(iid, f"Botón {iid}")
            
        elif itype == "axis":
            axis_names = {
                0: "Inclinación X (Wiimote)",
                1: "Inclinación Y (Wiimote)",
                2: "Inclinación Z (Wiimote)",
                3: "Yaw (Wiimote)",
                4: "Roll (Wiimote)",
                5: "Pitch (Wiimote)",
                6: "Inclinación X (Nunchuk)",
                7: "Inclinación Y (Nunchuk)",
                8: "Inclinación Z (Nunchuk)",
                116: "Palanca Nunchuk X", # ABS_HAT0X + 100 = 16 + 100 = 116
                117: "Palanca Nunchuk Y"  # ABS_HAT0Y + 100 = 17 + 100 = 117
            }
            return axis_names.get(iid, f"Eje {iid}")
            
        return f"{itype.capitalize()} {iid}"

    def flush(self):
        """Vacía las colas de todos los nodos y resetea el estado de botones."""
        for dev in self.nodes.values():
            try:
                while dev.read_one():
                    pass
            except (BlockingIOError, OSError):
                pass
        # Resetear estado para evitar binds fantasma
        self.state["buttons"] = {}
        self.state["nunchuk_axes"] = {}

    # --- Wiimote-specific methods ---

    def connect_wiimote(self):
        """Busca y agrega todos los nodos (Botones, Accel, IR, Nunchuk) del Wiimote detectado."""
        if not EVDEV_AVAILABLE:
            return False

        import os
        self.nodes = {}
        try:
            device_paths = evdev.list_devices()
            devices = [evdev.InputDevice(p) for p in device_paths]

            # Buscamos patrones comunes: RVL, Nintendo, Remote
            potential_nodes = [
                d for d in devices
                if "Nintendo" in d.name and ("RVL" in d.name or "Remote" in d.name or "Nunchuk" in d.name)
            ]

            if not potential_nodes:
                return False

            # Intentar agrupar por phys, o por parent sysfs si phys falla
            first_node = potential_nodes[0]
            group_id = first_node.phys
            use_sysfs = not group_id

            if use_sysfs:
                # En Linux, devices de un mismo Wiimote suelen compartir el parent path en sysfs
                try:
                    evt_name = os.path.basename(first_node.path)
                    group_id = os.path.dirname(os.path.realpath(f"/sys/class/input/{evt_name}/device"))
                except Exception:
                    group_id = "unknown"

            for d in potential_nodes:
                match = False
                if not use_sysfs:
                    match = (d.phys == group_id)
                else:
                    try:
                        d_evt = os.path.basename(d.path)
                        d_group = os.path.dirname(os.path.realpath(f"/sys/class/input/{d_evt}/device"))
                        match = (d_group == group_id)
                    except Exception:
                        match = False

                if match:
                    # Clasificar
                    tag = "other"
                    name_lower = d.name.lower()
                    if "nunchuk" in name_lower:
                        if "accelerometer" in name_lower:
                            tag = "nunchuk_accel"
                        else:
                            tag = "nunchuk"
                    elif "accelerometer" in name_lower: tag = "accel"
                    elif "motion plus" in name_lower or "motionplus" in name_lower: tag = "gyro"
                    elif "ir" in name_lower: tag = "ir"
                    elif "remote" in name_lower: tag = "buttons"
                    
                    if tag == "other":
                        tag = f"other_{d.fd}"
                        
                    self.nodes[tag] = d

            if self.nodes:
                self.active = True
                print(f"[Input/Wiimote] Detectado con {len(self.nodes)} nodos (Group: {group_id})")
                return True
        except Exception as e:
            print(f"[Input/Wiimote] Error detectando nodos: {e}")

        return False

    def start_pairing(self, callback=None):
        """
        Fase 1: Escanear vía bluetoothctl.
        Fase 2: Detectar nodos udev.
        """
        if self.is_pairing:
            return
        self.is_pairing = True

        def run():
            found = False
            print("[Input/Wiimote] Iniciando escaneo de Wiimotes...")
            try:
                subprocess.run(
                    ["bluetoothctl", "--timeout", "10", "scan", "on"],
                    capture_output=True
                )
                # Esperar a que el driver cargue los nodos
                time.sleep(2)
                found = self.connect_wiimote()
            except Exception as e:
                print(f"[Input/Wiimote] Error en pairing: {e}")

            self.is_pairing = False
            if callback:
                callback(found)

        threading.Thread(target=run, daemon=True).start()
