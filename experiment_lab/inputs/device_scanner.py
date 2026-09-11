"""
device_scanner.py — Detección y clasificación de dispositivos de entrada.

Escanea el sistema buscando dispositivos vía múltiples backends (drivers),
los clasifica por categoría visual (Xbox, PS5, Joycons, Wiimote, etc.).

Drivers soportados:
  - Pygame   (Cross-platform, estándar)
  - SDL2     (Cross-platform, bajo nivel vía pysdl2)
  - Evdev    (Linux, lectura directa /dev/input/eventX)
  - XInput   (Windows, API nativa para mandos Xbox)
  - LinuxRaw (Linux, lectura clásica /dev/input/jsX)
  - DirectInput (Windows, API clásica — placeholder)
"""

import os

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

try:
    import evdev
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False

try:
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    import sdl2
    SDL2_AVAILABLE = True
except ImportError:
    SDL2_AVAILABLE = False

XINPUT_AVAILABLE = False
if os.name == 'nt':
    try:
        import ctypes
        if hasattr(ctypes, 'windll'):
            try:
                ctypes.windll.xinput1_4
                XINPUT_AVAILABLE = True
            except (AttributeError, OSError):
                try:
                    ctypes.windll.xinput1_3
                    XINPUT_AVAILABLE = True
                except (AttributeError, OSError):
                    pass
    except ImportError:
        pass


def get_available_drivers():
    """
    Retorna una lista de drivers de entrada disponibles en el sistema actual.
    Solo incluye drivers cuyas dependencias están instaladas.
    """
    drivers = []

    if PYGAME_AVAILABLE:
        drivers.append("Pygame")
    if SDL2_AVAILABLE:
        drivers.append("SDL2")
    if EVDEV_AVAILABLE:
        drivers.append("Evdev")
    if XINPUT_AVAILABLE:
        drivers.append("XInput")
    if os.name != 'nt':
        drivers.append("LinuxRaw")
    else:
        drivers.append("DirectInput")

    # Siempre debe haber al menos uno; fallback
    if not drivers:
        drivers.append("Pygame")

    return drivers


def _classify_device(categories, dinfo, lower_name):
    """Clasifica un dispositivo en la categoría correcta según su nombre.
    
    Todos los dispositivos detectados se listan sin filtros.
    El usuario elige libremente qué backend y categoría usar.
    """
    if "xbox" in lower_name or "xinput" in lower_name:
        categories["Mando Xbox"].append(dinfo)
    elif any(k in lower_name for k in ("ps5", "sony", "dualshock", "dualsense")):
        categories["Mando PS5"].append(dinfo)
    elif "joy-con" in lower_name or "joycon" in lower_name:
        categories["Nintendo Joycons"].append(dinfo)
    elif "nintendo" in lower_name or "rvl" in lower_name or "wii" in lower_name:
        # Las entradas crudas (de pygame/sdl2/evdev genérico) de Wiimote
        # se desvían a "Otros (Custom)" para evitar duplicidad y ruido en la
        # pestaña exclusiva "Wiimote", la cual ya inyecta su propio nodo unificado (Multi-Nodo).
        categories["Otros (Custom)"].append(dinfo)
    else:
        categories["Otros (Custom)"].append(dinfo)


def _scan_pygame(categories):
    """Escanea gamepads vía Pygame (SDL2 wrapper de alto nivel)."""
    if not PYGAME_AVAILABLE:
        return
    try:
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        # Refrescar la detección
        pygame.joystick.quit()
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            joy = pygame.joystick.Joystick(i)
            name = joy.get_name()
            dinfo = {"id": f"JOY_{i}", "name": f"[Pygame] {name}"}
            _classify_device(categories, dinfo, name.lower())
    except Exception as e:
        print(f"[Scanner] Error escaneando Pygame: {e}")


def _scan_sdl2(categories):
    """Escanea gamepads vía SDL2 directo (pysdl2)."""
    if not SDL2_AVAILABLE:
        return
    try:
        sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_GAMECONTROLLER)
        for i in range(sdl2.SDL_NumJoysticks()):
            raw_name = sdl2.SDL_JoystickNameForIndex(i)
            name = raw_name.decode('utf-8') if raw_name else f"Joystick {i}"
            dinfo = {"id": f"SDL_{i}", "name": f"[SDL2] {name}"}
            _classify_device(categories, dinfo, name.lower())
    except Exception as e:
        print(f"[Scanner] Error escaneando SDL2: {e}")


def _scan_evdev(categories):
    """Escanea dispositivos de entrada vía evdev (Linux)."""
    if not EVDEV_AVAILABLE:
        return
    try:
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            dinfo = {"id": path, "name": f"[Evdev] {dev.name}"}
            _classify_device(categories, dinfo, dev.name.lower())
    except Exception as e:
        print(f"[Scanner] Error escaneando Evdev: {e}")


def _scan_xinput(categories):
    """Escanea mandos XInput (Windows, hasta 4 slots)."""
    if not XINPUT_AVAILABLE:
        return
    for i in range(4):
        name = f"XInput Controller {i}"
        dinfo = {"id": f"XIN_{i}", "name": f"[XInput] {name}"}
        _classify_device(categories, dinfo, name.lower())


def _scan_linuxraw(categories):
    """Escanea joysticks clásicos /dev/input/jsX."""
    for i in range(16):
        path = f"/dev/input/js{i}"
        if os.path.exists(path):
            # Intentar leer el nombre del dispositivo
            name = path
            try:
                import fcntl, array
                buf = array.array('B', [0] * 64)
                with open(path, 'rb') as f:
                    # JSIOCGNAME(len) = 0x80006a13 + (len << 16)
                    fcntl.ioctl(f, 0x80006a13 | (64 << 16), buf)
                name = buf.tobytes().split(b'\x00')[0].decode('utf-8')
            except Exception:
                pass
            dinfo = {"id": path, "name": f"[LinuxRaw] {name}"}
            _classify_device(categories, dinfo, name.lower())


def _scan_wiimote(categories):
    """Detecta Wiimotes conectados y añade la opción Multi-Nodo especializada.
    
    Esta entrada usa el WiimoteHandler que agrupa botones + acelerómetro +
    giroscopio + IR en un solo dispositivo lógico. Es una opción ADICIONAL
    a la que el driver de gamepad pueda listar como joystick genérico.
    """
    if not EVDEV_AVAILABLE:
        return
    try:
        seen_phys = set()
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            lower = dev.name.lower()
            # Solo buscar nodos del Wiimote principal (no accel/ir/gyro)
            if ("nintendo" in lower and ("wii" in lower or "rvl" in lower)
                    and "accelerometer" not in lower
                    and "ir" not in lower
                    and "motion plus" not in lower):
                group_key = dev.phys or dev.path
                if group_key not in seen_phys:
                    seen_phys.add(group_key)
                    categories["Wiimote"].append({
                        "id": "WIIMOTE_AUTO",
                        "name": f"★ {dev.name} (Multi-Nodo: Botones+Accel+Gyro)"
                    })
            dev.close()
    except Exception as e:
        print(f"[Scanner] Error escaneando Wiimote: {e}")


def _scan_midi(categories):
    """Escanea dispositivos MIDI (independiente del driver de gamepad)."""
    if not PYGAME_AVAILABLE:
        return
    try:
        # Ensure ALSA config path is set (Linux only — PortMidi uses ALSA sequencer).
        # PipeWire systems also need this because pipewire-alsa provides ALSA compat.
        import sys
        if sys.platform.startswith("linux") and not os.environ.get("ALSA_CONFIG_PATH"):
            for _p in ("/usr/share/alsa/alsa.conf", "/etc/alsa/alsa.conf", "/usr/local/share/alsa/alsa.conf"):
                if os.path.isfile(_p):
                    os.environ["ALSA_CONFIG_PATH"] = _p
                    break

        if not pygame.midi.get_init():
            pygame.midi.init()
        count = pygame.midi.get_count()
        for i in range(count):
            info = pygame.midi.get_device_info(i)
            if info and info[2] == 1:  # Is Input
                name = info[1].decode('utf-8') if info[1] else f"Device {i}"
                categories["MIDI"].append({
                    "id": str(i),
                    "name": f"MIDI: {name}"
                })
    except Exception as e:
        print(f"[Scanner] Error escaneando MIDI: {e}")


def _scan_serial(categories):
    """Escanea puertos seriales (independiente del driver de gamepad)."""
    if not SERIAL_AVAILABLE:
        return
    try:
        ports = serial.tools.list_ports.comports()
        for p in ports:
            categories["Serial"].append({
                "id": p.device,
                "name": f"Serial: {p.device} ({p.description})"
            })
    except Exception:
        pass


# Mapa de driver -> función de escaneo
_DRIVER_SCANNERS = {
    "Pygame": _scan_pygame,
    "SDL2": _scan_sdl2,
    "Evdev": _scan_evdev,
    "XInput": _scan_xinput,
    "LinuxRaw": _scan_linuxraw,
    "DirectInput": lambda cats: None,  # Placeholder — futuro
}


def get_categorized_devices(driver="Pygame"):
    """
    Retorna un diccionario de categorías con sus dispositivos detectados,
    usando el driver (backend) especificado para el escaneo de gamepads.

    Los dispositivos MIDI y Serial siempre se escanean independientemente.

    Args:
        driver: Nombre del backend a usar ("Pygame", "SDL2", "Evdev", etc.)

    Returns:
        dict: {"Categoría": [{"id": str, "name": str}, ...], ...}
    """
    categories = {
        "Teclado": [{"id": "KM", "name": "Teclado y Ratón Genérico"}],
        "Mando Xbox": [],
        "Mando PS5": [],
        "Nintendo Joycons": [],
        "Wiimote": [],
        "DSU": [{"id": "DSU", "name": "Servidor Cemuhook / Móvil"}],
        "MIDI": [],
        "Serial": [],
        "Otros (Custom)": []
    }

    # Ejecutar el escáner del driver seleccionado (solo gamepads)
    scanner = _DRIVER_SCANNERS.get(driver)
    if scanner:
        scanner(categories)
    else:
        print(f"[Scanner] Driver desconocido: {driver}")

    # Categorías con handler especializado — SIEMPRE se escanean
    # independientemente del driver de gamepad seleccionado.
    _scan_wiimote(categories)
    _scan_midi(categories)
    _scan_serial(categories)

    return categories
