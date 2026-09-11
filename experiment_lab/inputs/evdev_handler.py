"""
evdev_handler.py — Handler para lectura directa de nodos /dev/input/*.

Utilizado para Arduinos, Digikeys, o cualquier mando cuando el usuario
fuerza el modo RAW UDEV. Lee eventos EV_KEY y EV_ABS normalizados.
"""

from .base import BaseInputHandler

try:
    import evdev
    from evdev import ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False


class EvdevHandler(BaseInputHandler):
    """Handler para lectura RAW de dispositivos vía evdev (/dev/input/*)."""

    def __init__(self):
        self.device = None       # evdev.InputDevice
        self.device_id = None    # Path: "/dev/input/eventN"
        self.state = {"axes": {}, "buttons": {}}
        self.last_input = None

    def activate(self, device_id, **kwargs):
        """
        Abre un dispositivo evdev para lectura.
        
        Args:
            device_id: Path del dispositivo (ej: "/dev/input/event5").
        """
        if not EVDEV_AVAILABLE:
            print("[Input/Evdev] evdev no disponible")
            return

        self.device_id = device_id
        self.state = {"axes": {}, "buttons": {}}
        self.last_input = None

        try:
            self.device = evdev.InputDevice(device_id)
            print(f"[Input/Evdev] RAW Evdev Activado para {self.device.name}")
        except Exception as e:
            print(f"[Input/Evdev] Error activando {device_id}: {e}")
            self.device = None

    def deactivate(self):
        """Cierra el dispositivo evdev."""
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self.device_id = None
        self.state = {"axes": {}, "buttons": {}}
        self.last_input = None

    def poll(self):
        """Lee todos los eventos pendientes y actualiza el estado interno."""
        if not self.device:
            return

        try:
            while True:
                event = self.device.read_one()
                if event is None:
                    break
                if event.type == ecodes.EV_KEY:
                    self.state["buttons"][event.code] = event.value
                    if event.value == 1:
                        self.last_input = ("button", event.code)
                elif event.type == ecodes.EV_ABS:
                    info = self.device.absinfo(event.code)
                    if info and info.max > info.min:
                        norm = (event.value - info.min) / (info.max - info.min)
                        val = (norm * 2.0) - 1.0
                        self.state["axes"][event.code] = val
                        if abs(val) > 0.05:
                            self.last_input = ("axis", event.code)
        except (BlockingIOError, OSError):
            pass

    def read_bind(self, bind, deadzone=0.05):
        """
        Lee un bind del estado del dispositivo evdev.
        
        Args:
            bind: {"type": "button"|"axis", "id": evdev_code}.
            deadzone: Zona muerta para ejes.
        """
        if not bind or not self.device:
            return 0.0

        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "button":
            return float(self.state["buttons"].get(iid, 0))
        elif itype == "axis":
            val = self.state["axes"].get(iid, 0.0)
            # Si el valor es exactamente 0.0, siempre es neutral
            if val == 0.0:
                return 0.0
            return 0.0 if abs(val) < deadzone else val

        return 0.0

    def get_last_input(self):
        """Consume y retorna el último input detectado de evdev."""
        last = self.last_input
        self.last_input = None
        return last

    def flush(self):
        """Descarta todos los eventos pendientes."""
        if not self.device:
            return
        try:
            while self.device.read_one():
                pass
        except (BlockingIOError, OSError):
            pass
        self.last_input = None
