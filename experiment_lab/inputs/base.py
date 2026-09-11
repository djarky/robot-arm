"""
base.py — Interfaz abstracta para todos los handlers de entrada.

Cada handler especializado (pygame, evdev, wiimote, dsu) debe heredar
de BaseInputHandler e implementar estos métodos.
"""


class BaseInputHandler:
    """Interfaz base para backends de lectura de entrada."""

    def activate(self, device_id, **kwargs):
        """
        Inicializa el handler para el dispositivo dado.
        
        Args:
            device_id: Identificador del dispositivo (ej: "KM", "JOY_0", "/dev/input/event5").
            **kwargs: Parámetros adicionales específicos del handler.
        """
        raise NotImplementedError

    def deactivate(self):
        """Libera recursos del handler (cierra sockets, dispositivos, etc.)."""
        pass

    def poll(self):
        """
        Actualiza el estado interno leyendo eventos pendientes.
        Debe llamarse cada frame antes de read_bind().
        """
        pass

    def read_bind(self, bind, deadzone=0.1):
        """
        Lee el valor actual de un bind específico.
        
        Args:
            bind: Dict con {"type": "axis"|"button", "id": int}.
            deadzone: Zona muerta para ejes analógicos.
            
        Returns:
            float: Valor del bind (0.0-1.0 para botones, -1.0 a 1.0 para ejes).
        """
        return 0.0

    def is_bind_touched(self, bind):
        """
        Retorna True si el bind ha sido interactuado o tiene un estado inicializado.
        Para gamepads es siempre True, para MIDI sirve para evitar snaps antes de tocarlo.
        """
        return True

    def get_last_input(self):
        """
        Detecta y retorna el primer input nuevo (para el mapper dialog).
        
        Returns:
            tuple|None: ("button"|"axis", id) o None si no hay input.
        """
        return None

    def flush(self):
        """Descarta eventos obsoletos para evitar mappings fantasma."""
        pass

    def get_direct_inputs(self):
        """
        Para handlers con salida directa (Wiimote, DSU) que NO usan
        el sistema unificado de binds.
        
        Returns:
            tuple|None: (joy_inputs, actions, camera_inputs) o None si
                        este handler usa el resolver unificado.
        """
        return None
