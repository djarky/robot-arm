"""
manager.py — Orquestador central del sistema de entradas.

Coordina los handlers especializados (pygame, evdev, wiimote, dsu),
gestiona perfiles por dispositivo, y expone la API pública que
lab_main.py e input_mapper_dialog.py consumen.
"""

import json
import os

from .pygame_handler import PygameHandler
from .evdev_handler import EvdevHandler
from .wiimote_handler import WiimoteHandler
from .dsu_handler import DSUHandler
from .midi_handler import MIDIHandler
from .serial_handler import SerialHandler
from .sdl2_handler import SDL2Handler
from .xinput_handler import XInputHandler
from .linuxraw_handler import LinuxRawHandler
from .device_scanner import get_categorized_devices as _scan_devices, get_available_drivers as _get_drivers

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class InputManager:
    """
    Gestor Universal de Entradas para el Laboratorio de Experimentos.
    Soporta perfiles de mando, remapeo y delegación a handlers especializados.
    """

    def __init__(self):
        # Configuración persistente
        self.custom_mapping_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "custom_mapping.json"
        )
        self.active_category = "Teclado"
        self.active_device_id = "KM"
        self.custom_config = {
            "profiles": {},
            "active_category": "Teclado",
            "active_device_id": "KM"
        }
        self.load_custom_mapping()

        # Sincronizar estado inicial desde config cargada
        self.active_category = self.custom_config.get("active_category", "Teclado")
        self.active_device_id = self.custom_config.get("active_device_id", "KM")
        self.input_driver = self.custom_config.get("input_driver", "Pygame")

        # Crear handlers
        self._pygame_handler = PygameHandler()
        self._evdev_handler = EvdevHandler()
        self._wiimote_handler = WiimoteHandler()
        self._dsu_handler = DSUHandler()
        self._midi_handler = MIDIHandler()
        self._serial_handler = SerialHandler()
        self._sdl2_handler = SDL2Handler()
        self._xinput_handler = XInputHandler()
        self._linuxraw_handler = LinuxRawHandler()

        # Handler activo actualmente
        self._active_handler = None

        # Legacy compatibility attributes used by lab_main.py
        self.joystick = None
        self.initialized = False
        self.wiimote_active = False
        self.wiimote_nodes = []
        self.is_pairing = False
        self.custom_evdev = None
        self.available_devices = []

        # Inicializar pygame si está disponible
        if PYGAME_AVAILABLE:
            self._pygame_handler.ensure_pygame()

        # Activar dispositivo desde la config guardada
        self._activate_saved_device()

    def _activate_saved_device(self):
        """Activa el dispositivo que estaba guardado en la config."""
        self.set_active_device(self.active_category, self.active_device_id)

    # ===================================================================
    #  API PRINCIPAL — Usada por lab_main.py cada frame
    # ===================================================================

    def get_arm_inputs(self):
        """
        Retorna los valores de control para el brazo y la cámara según el dispositivo activo.
        
        Returns:
            tuple: (joy_inputs_list, actions_dict, camera_inputs_list)
        """
        if not self.active_device_id or not self._active_handler:
            # Sin dispositivo activo, vaciar pygame y retornar neutro
            if PYGAME_AVAILABLE:
                pygame.event.get()
            return [0.0] * 7, {}, [0.0] * 7

        # Handlers con salida directa (Wiimote, DSU)
        direct = self._active_handler.get_direct_inputs()
        if direct is not None:
            return direct

        # Handlers que usan el resolver unificado (Pygame, Evdev)
        self._active_handler.poll()

        # Resolver ejes
        inputs = {
            "base": self._resolve_unified_axis("base"),
            "shoulder": self._resolve_unified_axis("shoulder"),
            "elbow": self._resolve_unified_axis("elbow"),
            "j3": self._resolve_unified_axis("j3"),
            "j4": self._resolve_unified_axis("j4"),
            "j5": self._resolve_unified_axis("j5"),
            "gripper": self._resolve_unified_axis("gripper"),
        }

        # Resolver acciones
        actions = {
            "snapshot": self._read_raw_bind(self._get_bind("snapshot")) > 0.5,
            "reset": self._read_raw_bind(self._get_bind("reset")) > 0.5,
            "toggle_console": self._read_raw_bind(self._get_bind("toggle_console")) > 0.5,
            "fsm_play_pause": self._read_raw_bind(self._get_bind("fsm_play_pause")) > 0.5,
            "fsm_skip_forward": self._read_raw_bind(self._get_bind("fsm_skip_forward")) > 0.5,
            "fsm_skip_backward": self._read_raw_bind(self._get_bind("fsm_skip_backward")) > 0.5,
        }

        # Resolver binds personalizados para animaciones, poses y teclas especiales FSM
        binds_dict = self.get_current_binds().get("inputs", {})
        for act_name, bind_val in binds_dict.items():
            if act_name.startswith("custom_fsm_") or act_name.startswith("special_key_"):
                actions[act_name] = self._read_raw_bind(bind_val) > 0.5

        # Resolver cámara
        camera_inputs = [
            self._resolve_unified_axis("cam_x"),
            self._resolve_unified_axis("cam_y"),
            self._resolve_unified_axis("cam_z"),
            self._resolve_unified_axis("cam_zoom"),
            self._resolve_unified_axis("cam_pitch"),
            self._resolve_unified_axis("cam_roll"),
            self._resolve_unified_axis("cam_yaw"),
        ]

        return list(inputs.values()), actions, camera_inputs

    # ===================================================================
    #  RESOLVER UNIFICADO — Lectura de binds delegada al handler activo
    # ===================================================================

    def _get_bind(self, action_name):
        """Obtiene la configuración de bind para una acción."""
        return self.get_current_binds().get("inputs", {}).get(action_name)

    def _resolve_unified_axis(self, name_base):
        """
        Resuelve un eje virtual combinando un bind positivo y uno negativo.
        Ej: "base" lee "base_pos" y "base_neg" y retorna pos - neg.
        """
        binds = self.get_current_binds().get("inputs", {})
        pos_bind = binds.get(f"{name_base}_pos")
        neg_bind = binds.get(f"{name_base}_neg")

        pos_val = self._read_raw_bind(pos_bind)
        neg_val = self._read_raw_bind(neg_bind)

        return pos_val - neg_val

    def is_joint_axis_touched(self, name_base):
        """
        Retorna True si alguno de los binds (positivo o negativo) asignados a name_base
        ha sido tocado/interactuado en el handler activo.
        """
        binds = self.get_current_binds().get("inputs", {})
        pos_bind = binds.get(f"{name_base}_pos")
        neg_bind = binds.get(f"{name_base}_neg")

        if not pos_bind and not neg_bind:
            return False

        if self._active_handler:
            pos_touched = getattr(self._active_handler, 'is_bind_touched', lambda b: True)(pos_bind) if pos_bind else False
            neg_touched = getattr(self._active_handler, 'is_bind_touched', lambda b: True)(neg_bind) if neg_bind else False
            return pos_touched or neg_touched

        return True

    def _read_raw_bind(self, bind):
        """
        Lee el valor actual de un bind delegando al handler activo.
        """
        if not bind or not self._active_handler:
            return 0.0

        deadzone = self.get_current_binds().get("deadzone", 0.1)
        return self._active_handler.read_bind(bind, deadzone)

    # ===================================================================
    #  DETECCIÓN DE INPUT (para el Mapper Dialog)
    # ===================================================================

    def get_last_input(self):
        """
        Detecta y retorna el primer input (eje o botón).
        Delega al handler activo.
        """
        if not self._active_handler:
            return None
        return self._active_handler.get_last_input()

    def flush_queues(self):
        """Descarta eventos obsoletos para evitar mappings fantasma."""
        if PYGAME_AVAILABLE:
            pygame.event.clear()
        if self._active_handler:
            self._active_handler.flush()

    def get_friendly_bind_name(self, bind):
        """
        Retorna una representación en texto amigable del bind.
        Delega al handler activo si posee lógica de traducción.
        """
        if not bind:
            return "SIN ASIGNAR"
        
        if self._active_handler and hasattr(self._active_handler, "get_friendly_bind_name"):
            return self._active_handler.get_friendly_bind_name(bind)
            
        # Formateador genérico por defecto
        t = bind.get("type", "bt")
        i = bind.get("id", "?")
        return f"{t.capitalize()} {i}"

    def inject_key_event(self, qt_key_code, pressed):
        """
        Inyecta un evento de teclado desde Qt al handler activo.
        Solo se procesa cuando el dispositivo activo es Teclado (KM).
        
        Args:
            qt_key_code: int — Código de tecla Qt (Qt.Key_*).
            pressed: bool — True si se presionó, False si se soltó.
        """
        # Solo inyectar si el dispositivo activo es Teclado
        if self.active_device_id != "KM":
            return
        self._pygame_handler.inject_key_event(qt_key_code, pressed)

    # ===================================================================
    #  GESTIÓN DE DISPOSITIVOS
    # ===================================================================

    def set_active_device(self, category, device_id):
        """
        Configura el dispositivo activo basándose en categoría e ID.
        Desactiva el handler anterior y activa el nuevo.
        """
        # Desactivar handler anterior
        if self._active_handler:
            self._active_handler.deactivate()
            self._active_handler = None

        self.active_category = category
        self.active_device_id = device_id

        print(f"[Input] Activando {category} -> {device_id}")

        if category == "Wiimote":
            self._active_handler = self._wiimote_handler
            self._active_handler.activate(device_id)
            # Legacy compat
            self.wiimote_active = self._wiimote_handler.active
            self.wiimote_nodes = self._wiimote_handler.nodes

        elif category == "DSU":
            self._active_handler = self._dsu_handler
            # Recuperar configuración de IP/Puerto
            host = self.custom_config.get("dsu_host", "127.0.0.1")
            port = self.custom_config.get("dsu_port", 26760)
            self._active_handler.activate(device_id, host=host, port=port)

        elif device_id == "KM":
            self._active_handler = self._pygame_handler
            self._active_handler.activate("KM")
            self.initialized = True

        elif str(device_id).startswith("JOY_"):
            self._active_handler = self._pygame_handler
            self._active_handler.activate(device_id)
            # Legacy compat
            self.joystick = self._pygame_handler.joystick
            self.initialized = self._pygame_handler.initialized

        elif str(device_id).startswith("SDL_"):
            self._active_handler = self._sdl2_handler
            self._active_handler.activate(device_id)
            self.initialized = True

        elif str(device_id).startswith("XIN_"):
            self._active_handler = self._xinput_handler
            self._active_handler.activate(device_id)
            self.initialized = True

        elif str(device_id).startswith("/dev/input/js"):
            self._active_handler = self._linuxraw_handler
            self._active_handler.activate(device_id)
            self.initialized = True

        elif str(device_id).startswith("/dev/input/"):
            self._active_handler = self._evdev_handler
            self._active_handler.activate(device_id)
            # Legacy compat
            self.custom_evdev = self._evdev_handler.device

        elif category == "MIDI":
            self._active_handler = self._midi_handler
            self._active_handler.activate(device_id)

        elif category == "Serial":
            self._active_handler = self._serial_handler
            baud = self.custom_config.get("serial_baud", 115200)
            self._active_handler.activate(device_id, baud=baud)

        # Actualizar legacy state
        self._sync_legacy_state()

    def _sync_legacy_state(self):
        """Sincroniza atributos legacy para compatibilidad con lab_main.py."""
        if isinstance(self._active_handler, PygameHandler):
            self.joystick = self._active_handler.joystick
            self.initialized = self._active_handler.initialized
        else:
            self.joystick = None

        if isinstance(self._active_handler, WiimoteHandler):
            self.wiimote_active = self._active_handler.active
            self.wiimote_nodes = self._active_handler.nodes
        else:
            self.wiimote_active = False

        if isinstance(self._active_handler, EvdevHandler):
            self.custom_evdev = self._active_handler.device
        else:
            self.custom_evdev = None

    def get_categorized_devices(self):
        """Retorna un diccionario de categorías con sus dispositivos detectados."""
        return _scan_devices(driver=self.input_driver)

    def get_available_drivers(self):
        """Retorna los drivers disponibles en el sistema actual."""
        return _get_drivers()

    # ===================================================================
    #  WIIMOTE PAIRING — Delegado al handler
    # ===================================================================

    def start_pairing(self, callback=None):
        """Inicia el proceso de emparejamiento del Wiimote."""
        self._wiimote_handler.start_pairing(callback)
        self.is_pairing = self._wiimote_handler.is_pairing

    def connect_wiimote(self):
        """Busca y conecta los nodos del Wiimote."""
        result = self._wiimote_handler.connect_wiimote()
        self.wiimote_active = self._wiimote_handler.active
        self.wiimote_nodes = self._wiimote_handler.nodes
        return result

    # ===================================================================
    #  PERFILES Y PERSISTENCIA
    # ===================================================================

    def load_custom_mapping(self):
        """Carga la configuración de perfiles desde el archivo JSON."""
        if os.path.exists(self.custom_mapping_path):
            try:
                with open(self.custom_mapping_path, "r") as f:
                    self.custom_config = json.load(f)
            except Exception as e:
                print(f"[Input] Error cargando custom_mapping: {e}")
                self._reset_custom_config()
        else:
            self._reset_custom_config()

    def _reset_custom_config(self):
        """Resetea la configuración a valores predeterminados."""
        self.custom_config = {
            "profiles": {},
            "deadzone": 0.1,
            "controller_style": "Xbox",
            "dsu_host": "127.0.0.1",
            "dsu_port": 26760
        }

    def get_current_binds(self):
        """Retorna el sub-diccionario de binds para el dispositivo activo."""
        dev_id = self.active_device_id
        if "profiles" not in self.custom_config:
            self.custom_config["profiles"] = {}

        if dev_id not in self.custom_config["profiles"]:
            # Inicializar perfil vacío para este hardware
            self.custom_config["profiles"][dev_id] = {"axes": {}, "buttons": {}}

        return self.custom_config["profiles"][dev_id]

    def save_custom_mapping(self, path=None):
        """Guarda la configuración de perfiles en el archivo JSON."""
        if path is None:
            path = self.custom_mapping_path

        # Actualizar estado global antes de guardar
        self.custom_config["active_category"] = self.active_category
        self.custom_config["active_device_id"] = self.active_device_id
        self.custom_config["input_driver"] = self.input_driver

        with open(path, "w") as f:
            json.dump(self.custom_config, f, indent=4)
        print(f"[Input] Configuración de perfiles guardada en {path}")
