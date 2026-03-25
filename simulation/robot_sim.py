import os
import socket
import json
import math
import time
from ursina import *
from panda3d.core import NodePath, Filename
from direct.actor.Actor import Actor
import gltf

from .entities import CircularJointSlider, TranslationGizmo

# Constants
DEFAULT_CAM_POS = (2.3, 3.54, -7.09)
DEFAULT_CAM_ROT = (-346.42, -18.57, 0)
GUI_ADDR = ("127.0.0.1", 5006)

class RobotArmSim:
    # Nombres de las juntas del modelo GLB (armadura "0arm")
    JOINT_NAMES = ["J0", "J1","J2", "J3", "J4", "J5"]
    NUM_JOINTS = 6

    def __init__(self):
        # Socket para enviar datos de vuelta a la GUI
        self.feedback_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Escenario básico
        self.sky = Sky()
        self.floor = Entity(model='plane', scale=500, texture='white_cube', 
                          texture_scale=(50,50), color=color.gray, collider='box')

        # Ejes XYZ para orientación (Rojo=X, Verde=Y, Azul=Z)
        # Ajustado para Z-up: Verde(Y) es Horizontal adelante, Azul(Z) es Vertical arriba
        Entity(model='cube', color=color.red, scale=(5, 0.05, 0.05), position=(2.5, 0.05, 0))
        Entity(model='cube', color=color.green, scale=(0.05, 0.05, 5), position=(0, 0.05, 2.5))
        Entity(model='cube', color=color.blue, scale=(0.05, 5, 0.05), position=(0, 2.5, 0))

        # Root parent para mover todo el robot fácilmente (solicitud del usuario: moverlo más abajo)
        self.robot_root = Entity(position=(0, -1.0, 0) )

        # ── Iluminación ──
        # shadows=False es CRÍTICO para evitar Segmentation Fault en este entorno Linux.
        self.dir_light = DirectionalLight(color=color.rgb(255, 255, 255), y=5, z=-5, shadows=True)
        self.dir_light.look_at(self.robot_root)
        self.ambient_light = AmbientLight(color=color.rgba(150, 150, 150, 0.6))

        # ── Cargar modelo GLB con armadura ──
        # El archivo está en el directorio superior del paquete simulation
        base_dir = os.path.dirname(os.path.dirname(__file__))
        model_path = os.path.join(base_dir, "robot_arm_sha.glb" )
        
        # Cargamos el modelo usando la librería gltf directamente para evitar problemas con el registro de Panda3D
        from panda3d.core import NodePath
        panda_model_node = gltf.load_model(model_path)
        panda_model = NodePath(panda_model_node) # Envolver en NodePath es vital para Actor
        
        # Usamos copy=False para que Actor use el NodePath directamente en lugar de intentar recargarlo
        # a través del sistema de archivos interno de Panda3D (que suele fallar aquí).
        self.actor = Actor(panda_model, copy=False)
        
        # Para evitar duplicados si hay partes que Actor y panda_model comparten, 
        # y para asegurar que todo sea visible:
        self.actor_entity = Entity(parent=self.robot_root, texture='texture.png')
        
        # Emparentar el actor a la escena de Ursina
        self.actor.reparentTo(self.actor_entity)
        self.actor.setScale(1)
        self.actor.setPos(0, 0, 0)
        
        # También emparentamos el panda_model original por si tiene partes estáticas 
        # que el Actor no haya incluido (como la base fija)
        panda_model.reparentTo(self.actor_entity)
        
        # Depuración de partes y juntas
        print(f"=== Partnames: {self.actor.getPartNames()} ===")
        print("=== Juntas del modelo ===")
        self.actor.listJoints()

        # Obtener nodos controlables para cada junta
        self.joint_controls = {}
        self.rest_hprs = {}  # Guardar la rotación original (rest pose) de cada junta
        
        # Intentar obtener el nombre de la parte principal (usualmente 'modelRoot' o 'default')
        pnames = self.actor.getPartNames()
        primary_part = pnames[0] if pnames else "modelRoot"
        
        for jname in self.JOINT_NAMES:
            try:
                # Usar el nombre de la parte detectado
                ctrl = self.actor.controlJoint(None, primary_part, jname)
                self.joint_controls[jname] = ctrl
                self.rest_hprs[jname] = ctrl.getHpr()
                print(f"  controlJoint('{jname}') → OK | Rest HPR: {self.rest_hprs[jname]}")
            except Exception as e:
                print(f"  controlJoint('{jname}') → FALLO en parte '{primary_part}': {e}")

        # Eje de rotación por junta
        self.joint_axes = {
            "J0": "YAW",
            "J1": "ROLL",
            "J2": "ROLL",
            "J3": "YAW",
            "J4": "PITCH",
            "J5": "PITCH",
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
        
        self.spawned_objects = []
        
        # Instanciar el Gizmo
        self.gizmo = TranslationGizmo()
        
        # ── Añadir Sliders Circulares a cada junta ──
        self.joint_sliders = []
        for i, jname in enumerate(self.JOINT_NAMES):
            ctrl = self.joint_controls.get(jname)
            if ctrl:
                axis = self.joint_axes[jname]
                # El radio base de la geometría es 1, lo escalaremos con world_scale
                slider = CircularJointSlider(self, i, axis=axis, radius=1.0) 
                
                # Para que el slider esté EXACTAMENTE en el pivote de la junta,
                # usamos exposeJoint que nos da un nodo que sigue el hueso.
                # Lo emparentamos para que herede la posición/rotación del brazo.
                exposed_node = self.actor.exposeJoint(None, "modelRoot", jname)
                slider.parent = exposed_node
                slider.position = (0,0,0) # Centrado en la junta
                
                # El robot mide aprox 100 unidades según el diagnóstico.
                # Aumentamos a 12.0 según petición del usuario (150-200% del anterior 8.0)
                slider.world_scale = 12.0 
                
                self.joint_sliders.append(slider)

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
            if axis == "YAW":
                ctrl.setHpr(rest[0] + clamped, rest[1], rest[2])
            elif axis == "PITCH":
                ctrl.setHpr(rest[0], rest[1] + clamped, rest[2])
            elif axis == "ROLL":
                ctrl.setHpr(rest[0], rest[1], rest[2] + clamped)

    def _get_angle(self, joint_index):
        """Devuelve el ángulo actual de la junta dada por índice."""
        return self.angles[joint_index]

    def sync_to_gui(self):
        """Enviar ángulos actuales a la GUI para sincronizar sliders."""
        angles = [round(self._get_angle(i), 1) for i in range(self.NUM_JOINTS)]
        msg = json.dumps({"type": "sync_angles", "data": angles})
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except:
            pass

    def load_camera_config(self, reset=False):
        try:
            cam_cfg = None
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
            if not reset and os.path.exists(config_path):
                with open(config_path, "r") as f:
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
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
            
            config["camera"] = {
                "position": [self.cam.x, self.cam.y, self.cam.z],
                "rotation": [self.cam.rotation_x, self.cam.rotation_y, self.cam.rotation_z]
            }
            
            with open(config_path, "w") as f:
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
                        if parent_dir and not os.path.exists(parent_dir):
                            os.makedirs(parent_dir)
                            print(f"DEBUG: Creado directorio {parent_dir}")
                        
                        # Usar base (builtin de Ursina/Panda3D)
                        fn = Filename.fromOsSpecific(path)
                        base.win.saveScreenshot(fn) # type: ignore
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
                        self.gizmo.attach_to(mouse.hovered_entity)
                else:
                    # Deseleccionar al hacer clic en el vacío
                    self.gizmo.detach()

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
        for obj in self.spawned_objects:
            if obj != self.gizmo.target: # No aplicar gravedad/colisión moviendo con Gizmo
                # Gravedad
                vel_y = 5.0 * time.dt * obj.mass_value
                obj.y -= vel_y
                
                # Floor clamp
                floor_y = obj.scale_y / 2
                if obj.y < floor_y:
                    obj.y = floor_y
