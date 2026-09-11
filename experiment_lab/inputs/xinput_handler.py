"""
xinput_handler.py — Handler de entrada para mandos de Xbox en Windows vía XInput.
"""

import os
import ctypes
from .base import BaseInputHandler

class XInputHandler(BaseInputHandler):
    def __init__(self):
        self.lib = None
        self.device_index = 0
        self.initialized = False
        self.state = None

    def activate(self, device_id, **kwargs):
        if os.name != 'nt':
            print("[XInput] Error: Solo disponible en Windows.")
            return

        try:
            self.lib = ctypes.windll.xinput1_4
        except Exception:
            try:
                self.lib = ctypes.windll.xinput1_3
            except Exception:
                print("[XInput] Error: No se encontró xinput DLL.")
                return

        if str(device_id).startswith("XIN_"):
            self.device_index = int(device_id.split("_")[1])
            self.initialized = True
            print(f"[XInput] Activado mando {self.device_index}")

    def deactivate(self):
        self.initialized = False
        self.state = None

    def flush(self):
        self.poll()

    def poll(self):
        if not self.initialized: return
        
        class XINPUT_GAMEPAD(ctypes.Structure):
            _fields_ = [
                ("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short),
            ]

        class XINPUT_STATE(ctypes.Structure):
            _fields_ = [
                ("dwPacketNumber", ctypes.c_uint),
                ("Gamepad", XINPUT_GAMEPAD),
            ]

        state = XINPUT_STATE()
        res = self.lib.XInputGetState(self.device_index, ctypes.byref(state))
        if res == 0:
            self.state = state.Gamepad
        else:
            self.state = None

    def read_bind(self, bind, deadzone=0.1):
        if not self.state: return 0.0
        
        itype = bind.get("type")
        iid = bind.get("id")
        
        if itype == "axis":
            # Mapeo de ejes XInput
            axes = {
                0: self.state.sThumbLX / 32767.0,
                1: self.state.sThumbLY / 32767.0,
                2: self.state.sThumbRX / 32767.0,
                3: self.state.sThumbRY / 32767.0,
                4: self.state.bLeftTrigger / 255.0,
                5: self.state.bRightTrigger / 255.0,
            }
            val = axes.get(iid, 0.0)
            if abs(val) < deadzone: val = 0.0
            return val
            
        elif itype == "button":
            # Mapeo de botones (máscara de bits) alineado con la interfaz estándar
            btns = {
                0: 0x1000, # A
                1: 0x2000, # B
                2: 0x4000, # X
                3: 0x8000, # Y
                4: 0x0100, # LB
                5: 0x0200, # RB
                6: 0x0020, # Back
                7: 0x0010, # Start
                8: 0x0040, # L3 (Pulsar Stick Izq)
                9: 0x0080, # R3 (Pulsar Stick Der)
            }
            mask = btns.get(iid, 0)
            return 1.0 if (self.state.wButtons & mask) else 0.0

        elif itype == "hat":
            try:
                # iid: [hat_idx, component, direction]
                hat_idx, comp, direction = iid
                wButtons = self.state.wButtons
                if comp == 0:  # Eje X de la cruceta (Izquierda / Derecha)
                    if direction > 0:
                        return 1.0 if (wButtons & 0x0008) else 0.0  # DPAD_RIGHT
                    else:
                        return 1.0 if (wButtons & 0x0004) else 0.0  # DPAD_LEFT
                elif comp == 1:  # Eje Y de la cruceta (Abajo / Arriba)
                    if direction > 0:
                        return 1.0 if (wButtons & 0x0001) else 0.0  # DPAD_UP
                    else:
                        return 1.0 if (wButtons & 0x0002) else 0.0  # DPAD_DOWN
            except (TypeError, ValueError, IndexError):
                return 0.0
            
        return 0.0

    def get_last_input(self):
        self.poll()  # ¡CRÍTICO: Refrescar el estado en cada poll de asignación!
        if not self.state: return None
        
        # 1. Botones principales
        btns = {
            0: 0x1000, # A
            1: 0x2000, # B
            2: 0x4000, # X
            3: 0x8000, # Y
            4: 0x0100, # LB
            5: 0x0200, # RB
            6: 0x0020, # Back
            7: 0x0010, # Start
            8: 0x0040, # L3
            9: 0x0080, # R3
        }
        for btn_id, mask in btns.items():
            if self.state.wButtons & mask:
                return ("button", btn_id)

        # 2. Cruceta / D-Pad (Hats)
        wButtons = self.state.wButtons
        if wButtons & 0x0001: return ("hat", [0, 1, 1])   # DPAD_UP
        if wButtons & 0x0002: return ("hat", [0, 1, -1])  # DPAD_DOWN
        if wButtons & 0x0004: return ("hat", [0, 0, -1])  # DPAD_LEFT
        if wButtons & 0x0008: return ("hat", [0, 0, 1])   # DPAD_RIGHT

        # 3. Ejes de Sticks y Gatillos
        lx = self.state.sThumbLX / 32767.0
        ly = self.state.sThumbLY / 32767.0
        rx = self.state.sThumbRX / 32767.0
        ry = self.state.sThumbRY / 32767.0
        lt = self.state.bLeftTrigger / 255.0
        rt = self.state.bRightTrigger / 255.0

        candidates = [
            (abs(lx), ("axis", 0)),
            (abs(ly), ("axis", 1)),
            (abs(rx), ("axis", 2)),
            (abs(ry), ("axis", 3)),
            (abs(lt), ("axis", 4)),
            (abs(rt), ("axis", 5)),
        ]
        valid_candidates = [c for c in candidates if c[0] > 0.5]
        if valid_candidates:
            # Retornar el que tenga la mayor desviación para evitar falsos positivos
            return max(valid_candidates, key=lambda x: x[0])[1]

        return None

    def get_friendly_bind_name(self, bind):
        """Retorna un nombre amigable en español para los botones, ejes y cruceta (hats) de XInput."""
        if not bind:
            return "SIN ASIGNAR"
        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "button":
            button_names = {
                0: "Botón A",
                1: "Botón B",
                2: "Botón X",
                3: "Botón Y",
                4: "LB (Mando)",
                5: "RB (Mando)",
                6: "Vista (Back)",
                7: "Menú (Start)",
                8: "Palanca Izq (L3)",
                9: "Palanca Der (R3)"
            }
            return button_names.get(iid, f"Botón {iid}")

        elif itype == "axis":
            axis_names = {
                0: "Palanca Izq X",
                1: "Palanca Izq Y",
                2: "Palanca Der X",
                3: "Palanca Der Y",
                4: "Gatillo Izq (LT)",
                5: "Gatillo Der (RT)"
            }
            return axis_names.get(iid, f"Eje {iid}")

        elif itype == "hat":
            try:
                hat_idx, comp, direction = iid
                hat_name = f"Cruceta {hat_idx} " if hat_idx > 0 else "Cruceta "
                if comp == 0:
                    dir_name = "Derecha" if direction > 0 else "Izquierda"
                else:
                    dir_name = "Arriba" if direction > 0 else "Abajo"
                return f"{hat_name}{dir_name}"
            except (TypeError, ValueError, IndexError):
                return f"Cruceta {iid}"

        return f"{itype.capitalize()} {iid}"
