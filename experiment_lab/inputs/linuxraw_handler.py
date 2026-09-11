"""
linuxraw_handler.py — Handler de entrada clásico para Linux (/dev/input/jsX).
"""

import os
import struct
import select
from .base import BaseInputHandler

class LinuxRawHandler(BaseInputHandler):
    def __init__(self):
        self.fd = None
        self.device_path = None
        self.axes = {}
        self.buttons = {}
        self.initialized = False

    def activate(self, device_id, **kwargs):
        if os.name == 'nt': return
        
        try:
            self.device_path = device_id
            self.fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
            self.initialized = True
            print(f"[LinuxRaw] Activado {self.device_path}")
        except Exception as e:
            print(f"[LinuxRaw] Error al abrir {device_id}: {e}")

    def deactivate(self):
        if self.fd:
            os.close(self.fd)
        self.initialized = False

    def poll(self):
        if not self.initialized: return
        
        while True:
            try:
                # El formato de joystick clásico de Linux es 8 bytes:
                # time (4), value (2), type (1), number (1)
                buf = os.read(self.fd, 8)
                if not buf: break
                
                t, val, itype, iid = struct.unpack('IhBB', buf)
                
                # itype 0x01 es botón, 0x02 es eje. (0x80 es init bit)
                real_type = itype & ~0x80
                
                if real_type == 0x01:
                    self.buttons[iid] = 1.0 if val else 0.0
                elif real_type == 0x02:
                    self.axes[iid] = val / 32767.0
                    
            except (BlockingIOError, OSError):
                break

    def read_bind(self, bind, deadzone=0.1):
        itype = bind.get("type")
        iid = bind.get("id")
        
        if itype == "axis":
            val = self.axes.get(iid, 0.0)
            if abs(val) < deadzone: val = 0.0
            return val
        elif itype == "button":
            return self.buttons.get(iid, 0.0)
        return 0.0

    def get_last_input(self):
        for aid, val in self.axes.items():
            if abs(val) > 0.5: return ("axis", aid)
        for bid, val in self.buttons.items():
            if val > 0.5: return ("button", bid)
        return None

    def flush(self):
        # En JS raw, el flush es simplemente vaciar el buffer de lectura
        self.poll()
        self.axes = {}
        self.buttons = {}
