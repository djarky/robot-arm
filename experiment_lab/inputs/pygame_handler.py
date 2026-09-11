"""
pygame_handler.py — Handler para Teclado y Mandos genéricos vía Pygame.

Maneja dos sub-modos:
  - Teclado ("KM"): Recibe eventos de teclas inyectados desde Qt (keyPressEvent/keyReleaseEvent).
    pygame.key.get_pressed() NO funciona en apps Qt porque no hay ventana pygame con foco.
  - Joystick ("JOY_*"): Lee joystick.get_axis() y get_button() vía pygame.

Ambos comparten pygame.event.get() para el polling de joysticks.
"""

from collections import deque
from .base import BaseInputHandler

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class PygameHandler(BaseInputHandler):
    """Handler unificado para Teclado/Mouse y Mandos genéricos vía Pygame."""

    def __init__(self):
        self.joystick = None
        self.initialized = False
        self.mode = None          # "KM" o "JOY"
        self.device_id = None
        self._pygame_inited = False
        self.last_input = None

        # Estado de teclas inyectadas desde Qt (reemplaza pygame.key.get_pressed)
        self._pressed_keys = set()       # Set de key codes actualmente presionados
        self._key_event_queue = deque(maxlen=32)  # Cola de teclas recién presionadas para get_last_input

    def ensure_pygame(self):
        """Inicializa pygame si aún no se ha hecho."""
        if not PYGAME_AVAILABLE:
            return False
        if not self._pygame_inited:
            pygame.init()
            pygame.joystick.init()
            self._pygame_inited = True
        return True

    def activate(self, device_id, **kwargs):
        """
        Activa el handler.
        
        Args:
            device_id: "KM" para teclado, "JOY_N" para joystick N.
        """
        self.last_input = None
        if not self.ensure_pygame():
            if device_id == "KM":
                # KM puede funcionar sin pygame (usa Qt key events)
                self.mode = "KM"
                self.device_id = device_id
                self.initialized = True
                self._pressed_keys.clear()
                self._key_event_queue.clear()
                print("[Input/Pygame] Modo Teclado activado (Qt events)")
                return
            return

        self.device_id = device_id

        if device_id == "KM":
            self.mode = "KM"
            self.joystick = None
            self.initialized = True
            self._pressed_keys.clear()
            self._key_event_queue.clear()
            print("[Input/Pygame] Modo Teclado activado (Qt events)")
        elif str(device_id).startswith("JOY_"):
            self.mode = "JOY"
            try:
                idx = int(str(device_id).split("_")[1])
                pygame.joystick.init()
                self.joystick = pygame.joystick.Joystick(idx)
                self.joystick.init()
                self.initialized = True
                print(f"[Input/Pygame] Joystick activado: {self.joystick.get_name()}")
            except Exception as e:
                print(f"[Input/Pygame] Error activando joystick {device_id}: {e}")
                self.joystick = None
                self.initialized = False

    def deactivate(self):
        """Libera el joystick actual y limpia estado de teclas."""
        self.joystick = None
        self.initialized = False
        self.mode = None
        self.device_id = None
        self.last_input = None
        self._pressed_keys.clear()
        self._key_event_queue.clear()

    def poll(self):
        """Consume la cola de eventos de pygame (para joysticks)."""
        if not PYGAME_AVAILABLE:
            return
        
        # Procesar eventos para el estado del joystick y capturar last_input
        for ev in pygame.event.get():
            if self.mode == "JOY":
                if ev.type == pygame.JOYBUTTONDOWN:
                    self.last_input = ("button", ev.button)
                elif ev.type == pygame.JOYAXISMOTION:
                    if abs(ev.value) > 0.15:  # Filtro de ruido
                        self.last_input = ("axis", ev.axis)
                elif ev.type == pygame.JOYHATMOTION:
                    hx, hy = ev.value
                    if hx != 0:
                        self.last_input = ("hat", [ev.hat, 0, 1 if hx > 0 else -1])
                    elif hy != 0:
                        self.last_input = ("hat", [ev.hat, 1, 1 if hy > 0 else -1])

    # =================================================================
    #  INYECCIÓN DE EVENTOS DE TECLADO DESDE QT
    # =================================================================

    def inject_key_event(self, qt_key_code, pressed):
        """
        Recibe un evento de tecla desde Qt (keyPressEvent/keyReleaseEvent).
        
        Args:
            qt_key_code: int — El código de tecla de Qt (Qt.Key_*).
            pressed: bool — True si se presionó, False si se soltó.
        """
        if pressed:
            if qt_key_code not in self._pressed_keys:
                self._pressed_keys.add(qt_key_code)
                self._key_event_queue.append(qt_key_code)
        else:
            self._pressed_keys.discard(qt_key_code)

    # =================================================================
    #  LECTURA DE BINDS
    # =================================================================

    def read_bind(self, bind, deadzone=0.1):
        """
        Lee el valor de un bind.
        
        Para modo KM: bind["id"] es un código de tecla Qt.
        Para modo JOY: bind["id"] es un índice de eje o botón de joystick, o una lista/tupla [hat_idx, component, direction] para hats.
        """
        if not bind:
            return 0.0

        itype = bind.get("type")
        iid = bind.get("id")

        if self.mode == "KM":
            # Teclado: verifica el estado inyectado desde Qt
            if itype == "button":
                return 1.0 if iid in self._pressed_keys else 0.0
            return 0.0

        elif self.mode == "JOY":
            if not PYGAME_AVAILABLE or not self.joystick:
                return 0.0
            if itype == "button":
                try:
                    return 1.0 if self.joystick.get_button(iid) else 0.0
                except (pygame.error, IndexError):
                    return 0.0
            elif itype == "axis":
                try:
                    val = self.joystick.get_axis(iid)
                    if val == 0.0:
                        return 0.0
                    return 0.0 if abs(val) < deadzone else val
                except (pygame.error, IndexError):
                    return 0.0
            elif itype == "hat":
                try:
                    hat_idx, comp, direction = iid
                    hat_val = self.joystick.get_hat(hat_idx)
                    val = hat_val[comp]
                    # Si direction > 0, buscamos valores positivos; si < 0, negativos
                    if direction > 0:
                        return 1.0 if val > 0 else 0.0
                    else:
                        return 1.0 if val < 0 else 0.0
                except (pygame.error, IndexError, TypeError, ValueError):
                    return 0.0

        return 0.0

    def get_last_input(self):
        """
        Detecta el primer input nuevo — estrictamente aislado por modo.
        
        KM: Solo detecta teclas inyectadas desde Qt.
        JOY: Retorna y consume el último input del joystick detectado en poll().
        """
        if self.mode == "KM":
            # Solo teclado — nunca joystick
            if self._key_event_queue:
                key_code = self._key_event_queue.popleft()
                return ("button", key_code)

        elif self.mode == "JOY":
            last = self.last_input
            self.last_input = None
            return last

        return None

    def get_friendly_bind_name(self, bind):
        """Retorna un nombre amigable en español para los botones, ejes y cruceta (hats)."""
        if not bind:
            return "SIN ASIGNAR"
        itype = bind.get("type")
        iid = bind.get("id")

        # Modo Teclado: los IDs son códigos Qt.Key_*, no índices de joystick
        if self.mode == "KM" and itype == "button":
            from .qt_key_names import get_qt_key_name
            return f"Tecla {get_qt_key_name(iid)}"

        if itype == "button":
            button_names = {
                0: "Botón A",
                1: "Botón B",
                2: "Botón X",
                3: "Botón Y",
                4: "LB (Mando)",
                5: "RB (Mando)",
                6: "Vista (Mando)",
                7: "Menú (Mando)",
                8: "Palanca Izq (L3)",
                9: "Palanca Der (R3)",
                10: "Guía (Xbox)"
            }
            return button_names.get(iid, f"Botón {iid}")

        elif itype == "axis":
            axis_names = {
                0: "Palanca Izq X",
                1: "Palanca Izq Y",
                2: "Gatillo Izq (LT)",
                3: "Palanca Der X",
                4: "Palanca Der Y",
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

    def flush(self):
        """Limpia la cola de eventos de pygame y el estado de teclas."""
        if PYGAME_AVAILABLE:
            pygame.event.clear()
        self._key_event_queue.clear()
        self.last_input = None
        # NO limpiamos _pressed_keys — eso reflejaría un estado incorrecto
        # si el usuario tiene una tecla aún presionada.

    def refresh_joysticks(self):
        """Refresca la lista de joysticks detectados por pygame."""
        if not PYGAME_AVAILABLE:
            return
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count > 0 and not self.joystick:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            self.initialized = True
            print(f"[Input/Pygame] Mando detectado: {self.joystick.get_name()}")
