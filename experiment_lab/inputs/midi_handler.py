"""
midi_handler.py — Backend para lectura de controladores MIDI.

Usa pygame.midi (PortMidi) para capturar eventos de Control Change (ejes)
y Note On/Off (botones).

Compatibilidad:
  - Linux: PortMidi accede vía ALSA sequencer. PipeWire provee compatibilidad
    ALSA a través de pipewire-alsa, por lo que funciona transparentemente.
    El único requisito es que alsa.conf exista y ALSA_CONFIG_PATH apunte a él.
  - macOS: PortMidi usa CoreMIDI (no requiere ALSA).
  - Windows: PortMidi usa MMSystem/WinMM (no requiere ALSA).
"""

import os
import sys
import time
import threading

# --- Fix ALSA config path (Linux only) ---
# PortMidi (used by pygame.midi) links against libasound (ALSA).
# When ALSA is compiled with a default prefix of /usr/local, it looks for
# alsa.conf in /usr/local/share/alsa/, but distros install it in /usr/share/alsa/.
# PipeWire systems still need this because pipewire-alsa provides an ALSA
# compatibility layer that relies on the same alsa.conf being accessible.
# This fix is safe on all platforms: on macOS/Windows os.path.isfile returns False.
if sys.platform.startswith("linux") and not os.environ.get("ALSA_CONFIG_PATH"):
    _alsa_candidates = [
        "/usr/share/alsa/alsa.conf",       # Debian, Ubuntu, Fedora, Arch, OpenSUSE
        "/etc/alsa/alsa.conf",             # Some custom installations
        "/usr/local/share/alsa/alsa.conf",  # Source-compiled ALSA
    ]
    for _p in _alsa_candidates:
        if os.path.isfile(_p):
            os.environ["ALSA_CONFIG_PATH"] = _p
            break

try:
    import pygame.midi
    MIDI_AVAILABLE = True
except ImportError:
    MIDI_AVAILABLE = False

from .base import BaseInputHandler

# Umbral mínimo de cambio en valor CC para considerar que un control se movió.
# Valores CC van de 0-127, normalizados a -1.0..1.0, así que un delta de 0.05
# equivale a ~3 unidades MIDI — suficiente para filtrar jitter pero sensible
# al movimiento real de un potenciómetro o encoder.
CC_DELTA_THRESHOLD = 0.05


class MIDIHandler(BaseInputHandler):
    """Handler especializado para dispositivos MIDI (Teclados, Launchpads, Mixers, MidiStomp)."""

    def __init__(self):
        self.device = None
        self.device_id = None
        self.device_name = "MIDI"
        self.last_input = None
        self.axes_state = {}        # {cc_id: float} — valor actual normalizado
        self._prev_axes_state = {}  # {cc_id: float} — valor anterior para detección de delta
        self.buttons_state = {}     # {note_id: bool}
        self.initialized = False

    def activate(self, device_id, **kwargs):
        """
        Inicializa el dispositivo MIDI.
        device_id puede ser el índice del dispositivo en pygame.midi,
        o un string con el índice (como viene del device_scanner).

        PortMidi quirk: device IDs are assigned at init() time and become
        permanently invalid after the device is closed. To reliably reopen
        a device, we must do a full quit() + init() cycle, then find the
        device again by name (since IDs may shift).
        """
        if not MIDI_AVAILABLE:
            print("[MIDI] Error: pygame.midi no está disponible.")
            return

        # --- Cerrar dispositivo anterior si lo hay ---
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
            self.initialized = False

        # --- Full PortMidi reset: quit + init to get fresh device IDs ---
        try:
            if pygame.midi.get_init():
                pygame.midi.quit()
        except Exception:
            pass
        pygame.midi.init()

        count = pygame.midi.get_count()
        print(f"[MIDI] Dispositivos detectados: {count}")
        all_devices = []
        for i in range(count):
            info = pygame.midi.get_device_info(i)
            name = info[1].decode('utf-8') if info[1] else f"Device {i}"
            is_input = info[2] == 1
            direction = "INPUT" if is_input else "OUTPUT"
            print(f"  [{i}] {name} ({direction})")
            all_devices.append((i, name, is_input))

        try:
            target_idx = None

            if device_id == "MIDI_AUTO":
                # Buscar el primer input que no sea "Midi Through"
                for i, name, is_input in all_devices:
                    if is_input and "through" not in name.lower():
                        target_idx = i
                        break
                # Fallback al default
                if target_idx is None:
                    target_idx = pygame.midi.get_default_input_id()
                if target_idx == -1:
                    print("[MIDI] No se encontró dispositivo de entrada.")
                    return
            else:
                # device_id viene como string del scanner (ej: "3").
                # Pero tras el quit/init, los IDs pueden haber cambiado.
                # Estrategia: primero intentar por nombre, luego por índice.
                requested_idx = int(device_id)

                # Obtener el nombre que tenía el dispositivo con ese ID en el escaneo previo
                # (antes del quit/init). Buscamos por nombre en la lista actual.
                # Si el scanner guardó el nombre, lo usamos; si no, intentamos el ID directo.
                target_name = kwargs.get("device_name")

                if target_name:
                    # Buscar por nombre exacto (solo inputs)
                    for i, name, is_input in all_devices:
                        if is_input and name == target_name:
                            target_idx = i
                            break

                if target_idx is None:
                    # Fallback: intentar el ID directo si está en rango y es input
                    if 0 <= requested_idx < count:
                        info = pygame.midi.get_device_info(requested_idx)
                        if info[2] == 1:
                            target_idx = requested_idx

                if target_idx is None:
                    # Último recurso: buscar cualquier input que NO sea Midi Through
                    for i, name, is_input in all_devices:
                        if is_input and "through" not in name.lower():
                            target_idx = i
                            break

                if target_idx is None:
                    print(f"[MIDI] Error: No se pudo localizar dispositivo de entrada para ID={device_id}")
                    return

            # Validar que es input
            info = pygame.midi.get_device_info(target_idx)
            if info[2] != 1:
                print(f"[MIDI] Error: Device {target_idx} no es un dispositivo de entrada.")
                return

            dev_name = info[1].decode('utf-8') if info[1] else f"Device {target_idx}"
            self.device = pygame.midi.Input(target_idx)
            self.device_id = target_idx
            self.device_name = dev_name
            self.initialized = True
            print(f"[MIDI] ✓ Dispositivo activado: '{dev_name}' (ID: {target_idx})")
        except Exception as e:
            print(f"[MIDI] Error al abrir dispositivo {device_id}: {e}")
            self.initialized = False

    def deactivate(self):
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
        self.initialized = False
        # Quit PortMidi para liberar completamente los device IDs
        try:
            if MIDI_AVAILABLE and pygame.midi.get_init():
                pygame.midi.quit()
        except Exception:
            pass

    def poll(self):
        """Lee todos los eventos MIDI pendientes en el buffer.

        Para CC (ejes), se usa detección por delta: solo se reporta como
        `last_input` si el valor cambió significativamente respecto al
        anterior. Esto evita que jitter de potenciómetros interfiera con
        la detección de binds en el mapper.
        """
        if not self.initialized or not self.device:
            return

        while self.device.poll():
            events = self.device.read(10)  # Leer hasta 10 eventos
            for event in events:
                data, timestamp = event
                status, d1, d2, d3 = data

                msg_type = status & 0xF0
                channel = status & 0x0F

                # Control Change (CC) -> Ejes
                if msg_type == 0xB0:
                    val = (d2 / 127.0) * 2.0 - 1.0  # Normalizar a -1.0 a 1.0
                    prev_val = self._prev_axes_state.get(d1, 0.0)
                    delta = abs(val - prev_val)

                    self.axes_state[d1] = val

                    # Solo reportar como "último input" si el cambio es significativo
                    if delta >= CC_DELTA_THRESHOLD:
                        self._prev_axes_state[d1] = val
                        self.last_input = ("axis", d1)

                # Note On -> Botón Presionado
                elif msg_type == 0x90:
                    if d2 > 0:  # Velocity > 0 es Presionado
                        self.buttons_state[d1] = True
                        self.last_input = ("button", d1)
                    else:  # Velocity 0 es Soltado (equivalente a Note Off)
                        self.buttons_state[d1] = False

                # Note Off -> Botón Soltado
                elif msg_type == 0x80:
                    self.buttons_state[d1] = False

                # Program Change -> Botón momentáneo
                elif msg_type == 0xC0:
                    self.buttons_state[d1] = True
                    self.last_input = ("button", d1)

    def read_bind(self, bind, deadzone=0.1):
        if not bind:
            return 0.0

        itype = bind.get("type")
        iid = bind.get("id")

        if itype == "axis":
            val = self.axes_state.get(iid, 0.0)
            return val if abs(val) > deadzone else 0.0

        elif itype == "button":
            return 1.0 if self.buttons_state.get(iid, False) else 0.0

        return 0.0

    def is_bind_touched(self, bind):
        """Retorna True si el bind MIDI (CC o nota) ha sido registrado/tocado al menos una vez."""
        if not bind:
            return False
        itype = bind.get("type")
        iid = bind.get("id")
        if itype == "axis":
            return iid in self.axes_state
        elif itype == "button":
            return iid in self.buttons_state
        return False

    def get_last_input(self):
        """Consume y retorna el último input detectado.

        Antes de llamar a este método, se debe llamar a poll() para que
        haya eventos nuevos.
        """
        last = self.last_input
        self.last_input = None  # Consumir
        return last

    def get_friendly_bind_name(self, bind):
        """Retorna un nombre legible para un bind MIDI."""
        if not bind:
            return "SIN ASIGNAR"

        itype = bind.get("type", "?")
        iid = bind.get("id", "?")

        if itype == "axis":
            return f"CC {iid}"
        elif itype == "button":
            # Nombres de notas MIDI para referencia
            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            if isinstance(iid, int) and 0 <= iid <= 127:
                octave = (iid // 12) - 1
                note = note_names[iid % 12]
                return f"Nota {note}{octave} ({iid})"
            return f"Nota {iid}"

        return f"{itype} {iid}"

    def flush(self):
        if self.device:
            while self.device.poll():
                self.device.read(10)
        self.axes_state = {}
        self._prev_axes_state = {}
        self.buttons_state = {}
        self.last_input = None
