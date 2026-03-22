import sys
import socket
import json
import os
import math
from ursina import *
from panda3d.core import ConfigVariableString, NodePath
from direct.actor.Actor import Actor

# Configurar Ursina para incrustación o sin bordes dependiendo del SO
# Esto debe hacerse antes de instanciar Ursina()
if len(sys.argv) > 1:
    parent_window_id = sys.argv[1]
    # Intentar pasar el control de la ventana usando panda3d properties
    # En Windows, a veces es necesario pasar el ID de ventana de forma distinta o usar un formato específico
    if sys.platform == "win32":
        print(f"Windows: Intentando anclaje a {parent_window_id}")
    ConfigVariableString("parent-window-handle", parent_window_id).setValue(parent_window_id)
    print(f"Ursina intentando anclarse a la ventana: {parent_window_id}")

# Tomar ancho y alto pasados como argumento, por defecto 600x400
w = int(sys.argv[2]) if len(sys.argv) > 2 else 600
h = int(sys.argv[3]) if len(sys.argv) > 3 else 400

# Iniciamos Ursina con el tamaño del contenedor de PySide6 y forzando el origen
app = Ursina(size=(w, h), borderless=True)
window.position = (0, 0) # Forzar posición para evitar desfases al incrustar
window.color = color.light_gray

DEFAULT_CAM_POS = (2.3, 3.54, -7.09)
DEFAULT_CAM_ROT = (-346.42, -18.57, 0)

# Socket para enviar datos de vuelta a la GUI
feedback_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
GUI_ADDR = ("127.0.0.1", 5006)

class CircularSlider(Entity):
    def __init__(self, target_entity, axis='y', radius=0.8, slider_color=color.cyan, **kwargs):
        # Generar una "rosquilla" (toroide) ultra-estilizada y delgada
        segments = 100 # Resolución para suavidad
        path = [Vec3(math.cos(math.radians(i*(360/segments)))*radius, 0, math.sin(math.radians(i*(360/segments)))*radius) for i in range(segments + 1)]
            
        # Sección transversal cómoda y robusta
        thickness = 0.06 # Aumentado para máximo agarre y visibilidad
        cross_segments = 12
        # IMPORTANTE: Usar Vec3 para evitar el TypeError en el generador de Pipe interno
        cross_section = [Vec3(math.cos(math.radians(i*(360/cross_segments)))*thickness, math.sin(math.radians(i*(360/cross_segments)))*thickness, 0) for i in range(cross_segments + 1)]
        
        super().__init__(
            parent=target_entity,
            model=Pipe(path=path, base_shape=cross_section, cap_ends=False),
            color=color.rgba(slider_color.r, slider_color.g, slider_color.b, 0.4),
            double_sided=True,
            collider='mesh',
            **kwargs
        )
        # Forzar suavizado de malla y look de "luz"
        if self.model:
            self.model.generate_normals()
            self.model.smooth = True
            
        self.unlit = True 
        self.target = target_entity
        self.axis = axis
        self.radius = radius
        self.base_color = slider_color
        self.dragging = False
        self.pulse_time = 0

    def on_mouse_enter(self):
        self.color = color.rgba(1, 1, 1, 0.9)
        self.scale = 1.02 # Muy sutil
    
    def on_mouse_exit(self):
        if not self.dragging:
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)
            self.scale = 1.0

    def input(self, key):
        if key == 'left mouse down' and mouse.hovered_entity == self:
            self.dragging = True
            self.color = color.yellow
        elif key == 'left mouse up':
            self.dragging = False
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)
            self.scale = 1.0

    def update(self):
        # Efecto de pulso sutil (glow)
        self.pulse_time += time.dt * 2
        if not self.dragging:
            alpha = 0.3 + math.sin(self.pulse_time) * 0.1
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, alpha)

        if self.dragging:
            delta = mouse.velocity[0] + mouse.velocity[1]
            if self.axis == 'y':
                self.target.rotation_y = max(-90, min(90, self.target.rotation_y + delta * 500))
            else:
                self.target.rotation_x = max(-90, min(90, self.target.rotation_x - delta * 500))
            
            if hasattr(scene, 'sim_instance'):
                scene.sim_instance.sync_to_gui()

class TranslationGizmo(Entity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target = None
        
        # Color axes: Red=X, Green=Y, Blue=Z.
        axis_length = 1.5
        arrow_size = 0.2
        thick = 0.05
        
        # --- Eje X (Rojo) ---
        self.btn_x = Button(parent=self, model='cube', scale=(axis_length, thick, thick), position=(axis_length/2, 0, 0), color=color.red, collider='box')
        self.arrow_x = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(axis_length, 0, 0), color=color.red, rotation=(0, 90, 0))
        
        # --- Eje Y (Verde) ---
        self.btn_y = Button(parent=self, model='cube', scale=(thick, axis_length, thick), position=(0, axis_length/2, 0), color=color.green, collider='box')
        self.arrow_y = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(0, axis_length, 0), color=color.green, rotation=(-90, 0, 0))
        
        # --- Eje Z (Azul) ---
        self.btn_z = Button(parent=self, model='cube', scale=(thick, thick, axis_length), position=(0, 0, axis_length/2), color=color.blue, collider='box')
        self.arrow_z = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(0, 0, axis_length), color=color.blue, rotation=(0, 0, 0))

        # Configuraciones de botones
        for btn in (self.btn_x, self.btn_y, self.btn_z):
            btn.highlight_color = color.yellow
            btn.pressed_color = color.white
            btn.on_click = self.start_drag
        
        self.active_axis = None
        self.original_target_pos = None
        self.drag_start_mouse_y = 0
        self.drag_start_mouse_x = 0
        
        # Iniciar apagado
        self.disable()

    def update(self):
        if self.target and self.active_axis:
            # Calcular delta respecto al movimiento del ratón
            # Ursina normaliza la posición del mouse entre -0.5 y 0.5
            dx = mouse.x - self.drag_start_mouse_x
            dy = mouse.y - self.drag_start_mouse_y
            
            # Ajustar velocidad
            speed = 20
            
            new_pos = list(self.original_target_pos)
            if self.active_axis == 'x':
                new_pos[0] += dx * speed
            elif self.active_axis == 'y':
                new_pos[1] += dy * speed
            elif self.active_axis == 'z':
                # En Z usamos el movimiento vertical del ratón, igual que con Y, requiere sensibilidad
                new_pos[2] += dy * speed
                
            self.target.position = tuple(new_pos)
            self.position = self.target.position
            
        elif self.target:
            self.position = self.target.position

    def input(self, key):
        if key == 'left mouse up' and self.active_axis:
            self.stop_drag()
            
    def start_drag(self):
        self.active_axis = None
        if mouse.hovered_entity == self.btn_x: self.active_axis = 'x'
        elif mouse.hovered_entity == self.btn_y: self.active_axis = 'y'
        elif mouse.hovered_entity == self.btn_z: self.active_axis = 'z'
        
        if self.active_axis:
            self.original_target_pos = self.target.position
            self.drag_start_mouse_x = mouse.x
            self.drag_start_mouse_y = mouse.y
            
    def stop_drag(self):
        self.active_axis = None

    def attach_to(self, entity):
        self.target = entity
        self.position = entity.position
        self.enable()
        
    def detach(self):
        self.target = None
        self.disable()

    def delete_target(self):
        if self.target:
            obj = self.target
            self.detach() # Soltar el objeto
            
            # Quitar de la lista de la simulación
            if hasattr(scene, 'sim_instance') and obj in scene.sim_instance.spawned_objects:
                scene.sim_instance.spawned_objects.remove(obj)
                
            destroy(obj)

class RobotArmSim:
    # Nombres de las juntas del modelo GLB (armadura "0arm")
    JOINT_NAMES = ["J0", "J1","J2", "J3", "J4", "J5"]
    NUM_JOINTS = 6

    def __init__(self):
        # Escenario básico
        self.sky = Sky()
        self.floor = Entity(model='plane', scale=500, texture='white_cube', 
                          texture_scale=(50,50), color=color.gray, collider='box')

        # Ejes XYZ para orientación (Rojo=X, Verde=Y, Azul=Z)
        Entity(model='cube', color=color.red, scale=(5, 0.05, 0.05), position=(2.5, 0.05, 0))
        Entity(model='cube', color=color.green, scale=(0.05, 5, 0.05), position=(0, 2.5, 0))
        Entity(model='cube', color=color.blue, scale=(0.05, 0.05, 5), position=(0, 0.05, 2.5))

        # Root parent para mover todo el robot fácilmente (solicitud del usuario: moverlo más abajo)
        self.robot_root = Entity(position=(0, -1.0, 0) )

        # ── Iluminación ──
        # shadows=False es CRÍTICO para evitar Segmentation Fault en este entorno Linux.
        self.dir_light = DirectionalLight(color=color.rgb(255, 255, 255), y=5, z=-5, shadows=True)
        self.dir_light.look_at(self.robot_root)
        self.ambient_light = AmbientLight(color=color.rgba(150, 150, 150, 0.6))




        # ── Cargar modelo GLB con armadura ──
        model_path = os.path.join(os.path.dirname(__file__), "robot_arm_sha.glb" )
        
        # 1. Cargar el modelo estático para tener la base (pata4) que Actor descarta
        self.static_model = Entity(parent=self.robot_root , texture ='texture.png')

        
        try:
            panda_model = loader.loadModel(model_path)
            panda_model.reparentTo(self.static_model)
            for np in panda_model.findAllMatches("**/+GeomNode"):
                name = np.getName().lower()
        except Exception as e:
            print(f"Error cargando base estática: {e}")

        # 2. Cargar el Actor para las partes animadas
        self.actor = Actor(model_path )
        self.actor_entity = Entity(parent=self.robot_root , texture ='texture.png')
        self.actor.reparentTo(self.actor_entity)
        self.actor.setScale(1)
        self.actor.setPos(0, 0, 0)



        # Elemento UI para mostrar información de la junta
        #self.axis_text = Text(text="[Selecciona una junta (0-5)]", position=(-0.85, 0.45), scale=1.5, color=color.white)

        # Listar juntas para depuración
        print("=== Juntas del modelo ===")
        self.actor.listJoints()

        # Obtener nodos controlables para cada junta
        self.joint_controls = {}
        self.rest_hprs = {}  # Guardar la rotación original (rest pose) de cada junta
        for jname in self.JOINT_NAMES:
            try:
                ctrl = self.actor.controlJoint(None, "modelRoot", jname)
                self.joint_controls[jname] = ctrl
                self.rest_hprs[jname] = ctrl.getHpr()
                print(f"  controlJoint('{jname}') → OK | Rest HPR: {self.rest_hprs[jname]}")
            except Exception as e:
                print(f"  controlJoint('{jname}') → FALLO: {e}")

        # Eje de rotación por junta
        self.joint_axes = {
            "J0": "H",  # user request: H
            "J1": "R",
            "J2": "R",
            "J3": "R",
            "J4": "H",
            "J5": "P",  # user request: P
        }

        self.angles = [0] * self.NUM_JOINTS
        
        # Configuración de Cámara (EditorCamera) por defecto para que no se pierda el usuario
        self.cam = EditorCamera()
        self.cam.position = (0, 3, -8)  # Posición inicial cómoda
        self.cam.look_at(self.floor)
        
        # Networking (UDP receptor para no bloquear a la GUI principal)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permite reutilizar el puerto inmediatamente si se reinicia la app
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 5005))
        self.sock.setblocking(False)

        self.last_save_time = time.time()
        self.load_camera_config()
        
        self.selected_joint = None
        self.rotation_mode = False
        self.spawned_objects = []
        
        # Instanciar el Gizmo
        self.gizmo = TranslationGizmo()
        
        scene.sim_instance = self

    def _apply_angle(self, joint_index, angle_deg):
        """Aplica un ángulo (grados) a la junta dada por índice."""
        clamped = max(-90, min(90, angle_deg))
        self.angles[joint_index] = clamped
        jname = self.JOINT_NAMES[joint_index]
        ctrl = self.joint_controls.get(jname)
        if ctrl:
            axis = self.joint_axes[jname]
            rest = self.rest_hprs.get(jname, (0, 0, 0))
            if axis == "H":
                ctrl.setHpr(rest[0] + clamped, rest[1], rest[2])
            elif axis == "P":
                ctrl.setHpr(rest[0], rest[1] + clamped, rest[2])
            elif axis == "R":
                ctrl.setHpr(rest[0], rest[1], rest[2] + clamped)

    def _get_angle(self, joint_index):
        """Devuelve el ángulo actual de la junta dada por índice."""
        return self.angles[joint_index]

    def sync_to_gui(self):
        """Enviar ángulos actuales a la GUI para sincronizar sliders."""
        angles = [round(self._get_angle(i), 1) for i in range(self.NUM_JOINTS)]
        msg = json.dumps({"type": "sync_angles", "data": angles})
        try:
            feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except:
            pass

    def load_camera_config(self, reset=False):
        try:
            cam_cfg = None
            if not reset and os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
                    cam_cfg = config.get("camera")
            
            if cam_cfg:
                pos = cam_cfg.get("position")
                rot = cam_cfg.get("rotation")
                if pos: self.cam.position = tuple(pos)
                if rot: self.cam.rotation = tuple(rot)
            else:
                self.cam.position = DEFAULT_CAM_POS
                self.cam.rotation = DEFAULT_CAM_ROT
                
            if reset:
                print("Cámara reseteada a valores por defecto")
            else:
                print("Cámara restaurada desde config.json")
        except Exception as e:
            print(f"Error cargando config de cámara: {e}")
            self.cam.position = DEFAULT_CAM_POS
            self.cam.rotation = DEFAULT_CAM_ROT

    def save_camera_config(self):
        try:
            config = {}
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
            
            config["camera"] = {
                "position": [self.cam.x, self.cam.y, self.cam.z],
                "rotation": [self.cam.rotation_x, self.cam.rotation_y, self.cam.rotation_z]
            }
            
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error guardando config de cámara: {e}")

    def spawn_object(self, shape, size, mass):
        # Spawnea objetos a un lado del robot para interactuar
        obj = None
        spawn_pos = (2.5, 3, 0)
        
        # Construir geometría según la forma enviada
        if shape == "cube":
            obj = Entity(model='cube', scale=size, color=color.random_color(), position=spawn_pos, collider='box')
        elif shape == "cylinder":
            obj = Entity(model=Cylinder(resolution=16), scale=size, color=color.random_color(), position=spawn_pos, collider='mesh')
        elif shape == "sphere":
            obj = Entity(model='sphere', scale=size, color=color.random_color(), position=spawn_pos, collider='sphere')
        elif shape == "torus":
            # Usar un Pipe circular (parecido al CircularSlider) ya que Ursina no tiene 'torus'
            torus_path = [Vec3(math.cos(math.radians(i*(360/30))), 0, math.sin(math.radians(i*(360/30)))) for i in range(31)]
            cross_section = [Vec3(math.cos(math.radians(i*(360/8)))*0.2, math.sin(math.radians(i*(360/8)))*0.2, 0) for i in range(9)]
            try:
                obj = Entity(model=Pipe(path=torus_path, base_shape=cross_section, cap_ends=False), scale=size, color=color.random_color(), position=spawn_pos, collider='mesh')
                obj.model.generate_normals()
                obj.model.smooth = True
            except Exception:
                obj = Entity(model='sphere', scale=(size, size*0.5, size), color=color.random_color(), position=spawn_pos, collider='box')
                
        if obj:
            # Propiedad custom para poder detectarlos rápido al hacer click
            obj.is_spawned_toy = True
            obj.mass_value = mass # Para uso en posibles lógicas futuras
            self.spawned_objects.append(obj)

    def update(self):
        # Recibir mensajes de control de la GUI principal.
        # Leemos TODOS los paquetes en la cola hasta vaciarla para evitar lag.
        data_received = False
        last_data = None
        while True:
            try:
                data, _ = self.sock.recvfrom(1024)
                last_data = data
                data_received = True
            except BlockingIOError:
                break # No hay más mensajes en la cola

        if data_received and last_data:
            try:
                msg = json.loads(last_data.decode())
                if msg.get("type") == "angles":
                    incoming = msg["data"]
                    # Aplicar ángulos recibidos a las rotaciones (sobrescribe la entrada del ratón)
                    for i in range(min(len(incoming), self.NUM_JOINTS)):
                        self._apply_angle(i, incoming[i])
                elif msg.get("type") == "spawn":
                    self.spawn_object(msg["shape"], msg["size"], msg["mass"])
                elif msg.get("type") == "reset_camera":
                    self.load_camera_config(reset=True)
                elif msg.get("type") == "screenshot":
                    path = msg.get("path", "pose_thumb.png")
                    print(f"DEBUG: Sim recibio orden de screenshot. CWD: {os.getcwd()}")
                    print(f"DEBUG: Intentando guardar en: {path}")
                    
                    # Usar Panda3D directamente para mayor control
                    from panda3d.core import Filename
                    try:
                        # Asegurar que el directorio padre existe
                        parent_dir = os.path.dirname(path)
                        if not os.path.exists(parent_dir):
                            os.makedirs(parent_dir)
                            print(f"DEBUG: Creado directorio {parent_dir}")
                        
                        # Usar win.saveScreenshot para control total del nombre de archivo
                        # base.screenshot usa prefijos, win.saveScreenshot usa el path exacto
                        from panda3d.core import Filename
                        fn = Filename.fromOsSpecific(path)
                        base.win.saveScreenshot(fn)
                        print(f"DEBUG: win.saveScreenshot llamado hacia {path}")
                    except Exception as e:
                        print(f"DEBUG: Fallo al tomar screenshot: {e}")
            except Exception as e:
                print("Error decodificando UDP:", e)
                
        # Selección de objetos instanciados al hacer clic
        if mouse.left:
            # Evitar solapamientos si estamos arrastrando el gizmo
            if self.gizmo.active_axis is not None:
                pass
            else:
                if mouse.hovered_entity:
                    # Gizmo sobre un objeto ya seleccionado
                    if isinstance(mouse.hovered_entity, Button) and mouse.hovered_entity.parent == self.gizmo:
                        pass # El clic en el gizmo se procesa en el propio gizmo
                    # Objeto spawneado (toy)
                    elif hasattr(mouse.hovered_entity, 'is_spawned_toy'):
                        self.selected_joint = None
                        self.gizmo.attach_to(mouse.hovered_entity)
                else:
                    # Deseleccionar al hacer clic en el vacío
                    self.gizmo.detach()

        # Modo Rotación (Tecla R) — rota la junta seleccionada
        if held_keys['r'] and self.selected_joint is not None:
            self.rotation_mode = True
        
        if self.rotation_mode:
            delta = mouse.velocity[0] * 200
            if self.selected_joint is not None:
                cur = self._get_angle(self.selected_joint)
                self._apply_angle(self.selected_joint, cur + delta)
            
            self.sync_to_gui()
            
            if mouse.left: # Confirmar
                self.rotation_mode = False

        # Control manual de fallback con el ratón (shift + clic)
        if held_keys['shift']:
            if mouse.left:
                # Shift+Left: rota J0 (base) con movimiento horizontal
                cur = self._get_angle(0)
                self._apply_angle(0, cur + mouse.velocity[0] * 100)
                # y J1 con movimiento vertical
                cur1 = self._get_angle(1)
                self._apply_angle(1, cur1 - mouse.velocity[1] * 100)
            elif mouse.right:
                # Shift+Right: rota J3 (codo)
                cur2 = self._get_angle(2)
                self._apply_angle(2, cur2 - mouse.velocity[1] * 100)
            self.sync_to_gui()
        
        # Guardar posición de cámara cada 5 segundos si ha cambiado notablemente
        if time.time() - self.last_save_time > 5:
            self.save_camera_config()
            self.last_save_time = time.time()
            
        # --- Aplicar Fuerzas Físicas (Gravedad y Colisiones) ---
        # Como Ursina base no tiene un "collider" rígido que interactúe entre sí sin Bullet,
        # hacemos una pseudo-gravedad AABB (Bounding Box)
        
        # 1. Aplicamos gravedad tentativa a todos
        for obj in self.spawned_objects:
            if obj != self.gizmo.target: # No aplicar gravedad/colisión moviendo con Gizmo
                # Gravedad
                vel_y = 5.0 * time.dt * obj.mass_value
                obj.y -= vel_y
                
                # Floor clamp
                floor_y = obj.scale_y / 2
                if obj.y < floor_y:
                    obj.y = floor_y



    def select_joint(self, index):
        self.selected_joint = index
        jname = self.JOINT_NAMES[index] if index < self.NUM_JOINTS else '?'
        if jname != '?':
            axis = self.joint_axes[jname]
            axis_name = "Heading(Y)" if axis=="H" else "Pitch(X)" if axis=="P" else "Roll(Z)"
            self.axis_text.text = f"Junta: {jname}\nEje: {axis} - {axis_name}\n[A] Cambiar"
            print(f"Junta seleccionada: {jname} (Eje actual: {axis} - {axis_name}) [Presiona 'A' para cambiar eje]")

    def cycle_axis(self):
        if self.selected_joint is not None:
            jname = self.JOINT_NAMES[self.selected_joint]
            axes = ['H', 'P', 'R']
            current = self.joint_axes[jname]
            next_axis = axes[(axes.index(current) + 1) % 3]
            self.joint_axes[jname] = next_axis
            
            # Reset all rotations on the control node to its rest pose before reapplying on new axis
            ctrl = self.joint_controls.get(jname)
            if ctrl:
                rest = self.rest_hprs.get(jname, (0, 0, 0))
                ctrl.setHpr(rest[0], rest[1], rest[2])
            self._apply_angle(self.selected_joint, self.angles[self.selected_joint])
            
            axis_name = "Heading(Y)" if next_axis=="H" else "Pitch(X)" if next_axis=="P" else "Roll(Z)"
            self.axis_text.text = f"Junta: {jname}\nEje: {next_axis} - {axis_name}\n[A] Cambiar"
            print(f">>> Junta {jname} cambió a eje: {next_axis} ({axis_name})")

sim = RobotArmSim()

def update():
    sim.update()

def input(key):
    if key == 'delete':
        if sim.gizmo.enabled and sim.gizmo.target:
            sim.gizmo.delete_target()
    elif key == 'escape':
        if sim.gizmo.enabled:
            sim.gizmo.detach()
            sim.selected_joint = None
    # Selección de junta con teclas numéricas 0-4
    elif key in ['0', '1', '2', '3', '4','5']:
        idx = int(key)
        if idx < sim.NUM_JOINTS:
            sim.select_joint(idx)
    # Ciclar eje de rotación con tecla 'A'
    elif key == 'a':
        sim.cycle_axis()

# Bucle principal de Ursina
app.run()
