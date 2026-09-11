"""
sdl2_handler.py — Handler de entrada usando SDL2 directo vía pysdl2.
"""


from .base import BaseInputHandler

try:
    import sdl2
    import sdl2.ext
    SDL2_AVAILABLE = True
except ImportError:
    SDL2_AVAILABLE = False

import ctypes

class SDL2Handler(BaseInputHandler):
    def __init__(self):
        self.joystick = None
        self.controller = None
        self.initialized = False
        self.device_id = None
        self.axis_states = {}
        self.button_states = {}
        self.last_input = None

    def activate(self, device_id, **kwargs):
        if not SDL2_AVAILABLE:
            print("[SDL2] Error: pysdl2 no está instalado.")
            return

        sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_GAMECONTROLLER)
        self.device_id = device_id
        self.last_input = None
        
        if str(device_id).startswith("SDL_"):
            idx = int(device_id.split("_")[1])
            if sdl2.SDL_IsGameController(idx):
                self.controller = sdl2.SDL_GameControllerOpen(idx)
                print(f"[SDL2] GameController activado: {sdl2.SDL_GameControllerName(self.controller)}")
            else:
                self.joystick = sdl2.SDL_JoystickOpen(idx)
                print(f"[SDL2] Joystick activado: {sdl2.SDL_JoystickName(self.joystick)}")
            self.initialized = True

    def deactivate(self):
        if self.controller:
            sdl2.SDL_GameControllerClose(self.controller)
        if self.joystick:
            sdl2.SDL_JoystickClose(self.joystick)
        self.joystick = None
        self.controller = None
        self.initialized = False
        self.last_input = None

    def poll(self):
        if not self.initialized: return
        
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_CONTROLLERAXISMOTION:
                self.axis_states[event.caxis.axis] = event.caxis.value / 32767.0
                if abs(self.axis_states[event.caxis.axis]) > 0.5:
                    self.last_input = ("axis", event.caxis.axis)
            elif event.type == sdl2.SDL_CONTROLLERBUTTONDOWN:
                self.button_states[event.cbutton.button] = 1.0
                self.last_input = ("button", event.cbutton.button)
            elif event.type == sdl2.SDL_CONTROLLERBUTTONUP:
                self.button_states[event.cbutton.button] = 0.0
            elif event.type == sdl2.SDL_JOYAXISMOTION:
                self.axis_states[event.jaxis.axis] = event.jaxis.value / 32767.0
                if abs(self.axis_states[event.jaxis.axis]) > 0.5:
                    self.last_input = ("axis", event.jaxis.axis)
            elif event.type == sdl2.SDL_JOYBUTTONDOWN:
                self.button_states[event.jbutton.button] = 1.0
                self.last_input = ("button", event.jbutton.button)
            elif event.type == sdl2.SDL_JOYBUTTONUP:
                self.button_states[event.jbutton.button] = 0.0

    def read_bind(self, bind, deadzone=0.1):
        itype = bind.get("type")
        iid = bind.get("id")
        
        val = 0.0
        if itype == "axis":
            val = self.axis_states.get(iid, 0.0)
            if abs(val) < deadzone: val = 0.0
        elif itype == "button":
            val = self.button_states.get(iid, 0.0)
            
        return val

    def get_last_input(self):
        if not self.initialized: return None
        last = self.last_input
        self.last_input = None
        return last

    def flush(self):
        self.axis_states = {}
        self.button_states = {}
        self.last_input = None
        if self.initialized:
            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(ctypes.byref(event)):
                pass
