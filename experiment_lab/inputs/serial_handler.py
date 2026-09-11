"""
serial_handler.py — Backend para lectura de controladores Serial (Arduino/ESP32).

Escucha un puerto serial y parsea comandos simples:
A<id>:<val>  -> Eje (ej: A0:0.5)
B<id>:<0|1>  -> Botón (ej: B2:1)
"""

import threading
import queue
import time

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from .base import BaseInputHandler

class SerialHandler(BaseInputHandler):
    """Handler para controladores personalizados conectados vía Serial."""

    def __init__(self):
        self.ser = None
        self.port = None
        self.baud = 115200
        self.running = False
        self.read_thread = None
        self.input_queue = queue.Queue()
        
        self.axes_state = {}
        self.buttons_state = {}
        self.last_input = None

    def activate(self, device_id, **kwargs):
        """
        Activa la conexión serial.
        device_id: Nombre del puerto (ej: "/dev/ttyACM0" o "COM3").
        kwargs: 'baud' (int, default 115200).
        """
        if not SERIAL_AVAILABLE:
            print("[Serial] Error: pyserial no está instalado.")
            return

        self.deactivate() # Limpiar previo

        self.port = device_id
        self.baud = kwargs.get("baud", 115200)

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.running = True
            self.read_thread = threading.Thread(target=self._read_worker, daemon=True)
            self.read_thread.start()
            print(f"[Serial] Puerto {self.port} abierto a {self.baud} baudios.")
        except Exception as e:
            print(f"[Serial] Error al abrir {self.port}: {e}")
            self.ser = None

    def deactivate(self):
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=0.5)
            self.read_thread = None
        
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None

    def _read_worker(self):
        """Hilo dedicado a leer el puerto serial sin bloquear el GUI."""
        buffer = ""
        while self.running and self.ser:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        buffer = lines.pop() # El último puede estar incompleto
                        
                        for line in lines:
                            clean_line = line.strip()
                            if clean_line:
                                self.input_queue.put(clean_line)
                else:
                    time.sleep(0.001)
            except Exception as e:
                print(f"[Serial] Error en lectura: {e}")
                break

    def poll(self):
        """Procesa los mensajes acumulados en la cola."""
        while not self.input_queue.empty():
            line = self.input_queue.get()
            self._parse_line(line)

    def _parse_line(self, line):
        """
        Parser simple:
        A0:0.5  -> Axis 0, value 0.5 (se mapea de 0.0-1.0 a -1.0 a 1.0)
        B2:1    -> Button 2, pressed
        """
        try:
            if ":" not in line: return
            
            cmd, val_str = line.split(":", 1)
            prefix = cmd[0].upper()
            idx_str = cmd[1:]
            
            if not idx_str.isdigit(): return
            idx = int(idx_str)
            
            if prefix == 'A':
                # Eje: asumimos que el Arduino manda 0.0 a 1.0
                # Lo convertimos a -1.0 a 1.0
                raw_val = float(val_str)
                normalized = (raw_val * 2.0) - 1.0
                self.axes_state[idx] = normalized
                self.last_input = ("axis", idx)
            
            elif prefix == 'B':
                # Botón: 0 o 1
                pressed = int(val_str) > 0
                self.buttons_state[idx] = pressed
                if pressed:
                    self.last_input = ("button", idx)
        except Exception:
            # Ignorar líneas con formato inválido
            pass

    def read_bind(self, bind, deadzone=0.1):
        if not bind: return 0.0
        
        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "axis":
            val = self.axes_state.get(iid, 0.0)
            return val if abs(val) > deadzone else 0.0
        
        elif itype == "button":
            return 1.0 if self.buttons_state.get(iid, False) else 0.0

        return 0.0

    def get_last_input(self):
        last = self.last_input
        self.last_input = None
        return last

    def flush(self):
        while not self.input_queue.empty():
            self.input_queue.get()
        self.axes_state = {}
        self.buttons_state = {}
        self.last_input = None
