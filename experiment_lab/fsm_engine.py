import time

class FSMState:
    def __init__(self, name, pose_name, angles, transition_time=1.0):
        self.name = name
        self.pose_name = pose_name
        self.target_angles = angles
        self.transition_time = transition_time  # Time to reach this state's angles
        self.transitions = [] # List of dicts {type, params, next_state}

    def add_transition(self, trans_type, params, next_state):
        self.transitions.append({
            "type": trans_type, # 'time', 'key', 'sensor'
            "params": params,   # seconds, key_name, or condition
            "next": next_state
        })

class FSMEngine:
    """
    Motor de Máquina de Estados Finita (FSM) estilo Moore.
    Las salidas (ángulos) dependen únicamente del estado actual.
    """
    def __init__(self):
        self.states = {}
        self.current_state_name = None
        self.active = False
        self.start_state_name = None
        
        # Estado de ejecución
        self.start_time_in_state = 0
        self.last_angles = [0.0] * 5
        self.current_output = [0.0] * 5
        self.is_paused = False
        self.history = []

    def add_state(self, state_obj):
        self.states[state_obj.name] = state_obj
        if not self.start_state_name:
            self.start_state_name = state_obj.name

    def load_from_dict(self, data):
        """Carga una configuración completa desde un diccionario (JSON)."""
        self.states = {}
        self.start_state_name = data.get("entry_state")
        
        for name, info in data.get("states", {}).items():
            # info["angles"] puede ser el nombre de una pose o una lista directa
            angles = info.get("angles", [0.0]*5)
            state = FSMState(name, info.get("pose", "custom"), angles, info.get("transition_time", 1.0))
            for t in info.get("transitions", []):
                state.add_transition(t["type"], t["params"], t["next"])
            self.add_state(state)
        
        self.reset()

    def reset(self):
        self.current_state_name = self.start_state_name
        self.start_time_in_state = time.time()
        self.active = False
        self.history = []
        if self.current_state_name in self.states:
            angles = list(self.states[self.current_state_name].target_angles)
            # Ensure exactly 5 elements
            while len(angles) < 5: angles.append(0.0)
            self.current_output = angles[:5]
            self.last_angles = list(self.current_output)

    def start(self):
        if self.start_state_name:
            self.active = True
            self.is_paused = False
            self.start_time_in_state = time.time()
            self.history = []
            # Al empezar, si ya tenemos ángulos, los tomamos como punto de partida para la primera interpolación
            # last_angles se queda como lo que sea que tuviera el brazo
        else:
            print("[FSM] Error: No hay estado inicial definido.")

    def stop(self):
        self.active = False

    def toggle_pause(self):
        if not self.active: return
        self.is_paused = not self.is_paused
        # Si pausamos, registramos el tiempo transcurrido hasta ahora?
        # Para simplificar, ajustaremos start_time_in_state al reanudar
        if self.is_paused:
            self._pause_time = time.time()
        else:
            pause_duration = time.time() - self._pause_time
            self.start_time_in_state += pause_duration

    def update(self, external_inputs=None):
        """
        Actualiza el estado y devuelve los ángulos interpolados.
        external_inputs: dict con {'keys': set, 'sensors': dict}
        """
        if not self.active or self.is_paused or not self.current_state_name:
            return self.current_output

        state = self.states[self.current_state_name]
        now = time.time()
        elapsed = now - self.start_time_in_state

        # 1. Calcular Salida (Interpolación Moore-Transition)
        if state.transition_time > 0:
            t = min(1.0, elapsed / state.transition_time)
            # Suavizado simple (ease in/out) opcional
            # t = t * t * (3 - 2 * t) 
            for i in range(5):
                target = state.target_angles[i] if i < len(state.target_angles) else 0.0
                self.current_output[i] = self.last_angles[i] + (target - self.last_angles[i]) * t
        else:
            angles = list(state.target_angles)
            while len(angles) < 5: angles.append(0.0)
            self.current_output = angles[:5]

        # 2. Evaluar Transiciones
        for trans in state.transitions:
            triggered = False
            if trans["type"] == "time":
                if elapsed >= trans["params"]:
                    triggered = True
            elif trans["type"] == "key" and external_inputs:
                if trans["params"] in external_inputs.get("keys", []):
                    triggered = True
            elif trans["type"] == "sensor" and external_inputs:
                sensor_name = trans["params"]
                # Evaluar cualquier sensor que se envíe (ej: collision, sensor_obstaculo, etc)
                if external_inputs.get("sensors", {}).get(sensor_name):
                    triggered = True

            if triggered:
                if self.goto_state(trans["next"]):
                    break # Salir del bucle de transiciones para este frame

        return self.current_output

    def goto_state(self, next_name):
        if next_name in self.states:
            # Guardar el estado actual en la historia antes de cambiar
            if self.current_state_name and self.current_state_name != next_name:
                self.history.append(self.current_state_name)
            # Al cambiar de estado, guardamos la posición actual como punto de partida
            self.last_angles = list(self.current_output)
            self.current_state_name = next_name
            self.start_time_in_state = time.time()
            return True
        else:
            print(f"[FSM] Error: Estado '{next_name}' no encontrado.")
            return False

    def force_next(self):
        """Fuerza el paso al siguiente estado (primer transición disponible)."""
        if not self.current_state_name: return
        state = self.states[self.current_state_name]
        if state.transitions:
            self.goto_state(state.transitions[0]["next"])
        else:
            print("[FSM] Este estado no tiene transiciones de salida.")

    def force_prev(self):
        """Fuerza el regreso al estado/frame anterior en el historial."""
        if not self.history:
            print("[FSM] No hay estados anteriores en el historial.")
            return False
        prev_name = self.history.pop()
        if prev_name in self.states:
            self.last_angles = list(self.current_output)
            self.current_state_name = prev_name
            self.start_time_in_state = time.time()
            return True
        return False
