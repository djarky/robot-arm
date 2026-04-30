import os
import socket
import json
import math
import time
from ursina import *
from panda3d.core import NodePath, Filename, TransformState, LPoint3f, GeomVertexReader
from direct.actor.Actor import Actor
from panda3d.bullet import (BulletConvexHullShape, BulletTriangleMesh,
                             BulletTriangleMeshShape, BulletRigidBodyNode)
import gltf

from ursina.physics import PhysicsEntity, physics_handler
from .entities import CircularJointSlider, TransformationGizmo
from .collision_manager import CollisionManager
from .collision_aware_interpolator import CollisionAwareInterpolator

# Importar motores de SVG e IK (Asegurar que las rutas sean correctas)
from experiment_lab.svg_parser import SVGInterpreter
from .ik_engine import IK_Solver


from .robot_core import CameraMixin, SpawnMixin, CNCMixin, ArmControlMixin, NetworkMixin
from .robot_core.constants import GUI_ADDR, DEFAULT_CAM_POS, DEFAULT_CAM_ROT

class RobotArmSim(CameraMixin, SpawnMixin, CNCMixin, ArmControlMixin, NetworkMixin):
    # Nombres de las juntas del modelo GLB (armadura "0arm")
    JOINT_NAMES = ["J0", "J1","J2", "J3", "J4", "J5"]
    NUM_JOINTS = 6

    def __init__(self):
        # Socket para enviar datos de vuelta a la GUI
        self.feedback_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.feedback_sock.setblocking(False)
        
        # ── Configurar Motor de Físicas Bullet ──
        physics_handler.gravity = 50  # Escala del modelo ~100 unidades

        # Escenario básico
        self.sky = Sky()
        self.floor = Entity(
            model='cube', scale=(500, 1, 500), origin_y=0.5,
            texture='white_cube', texture_scale=(50, 50),
            color=color.gray, collider='box'
        )
        self.floor_physics = PhysicsEntity(
            model='cube', scale=(500, 1, 500), origin_y=0.5,
            mass=0, collider='box', visible=False
        )

        # Ejes XYZ para orientación (Rojo=X, Verde=Y, Azul=Z)
        # Ajustado para Z-up: Verde(Y) es Horizontal adelante, Azul(Z) es Vertical arriba
        Entity(model='cube', color=color.red, scale=(5, 0.05, 0.05), position=(2.5, 0.05, 0))
        Entity(model='cube', color=color.green, scale=(0.05, 0.05, 5), position=(0, 0.05, 2.5))
        Entity(model='cube', color=color.blue, scale=(0.05, 5, 0.05), position=(0, 2.5, 0))

        # --- SVG/CNC State ---
        self.ik_solver = IK_Solver()
        self.svg_interpreter = SVGInterpreter(scale=0.02) # Ajuste de escala por defecto
        self.svg_blueprint = None
        self.cnc_trajectory = [] # Lista de waypoints de mundo
        self.cnc_active = False
        self.cnc_index = 0
        self.cnc_feedrate = 1.5 # Unidades por segundo
        self.cnc_safety_height = 0.5 # Altura de levantamiento por defecto
        self.drawing_trace = Entity(model=Mesh(vertices=[], mode='line', thickness=3), color=color.green, always_on_top=True)
        self._trace_segments = []  # Lista de segmentos separados para el trazado

        # Root parent para mover todo el robot fácilmente (solicitud del usuario: moverlo más abajo)
        self.robot_root = Entity(position=(0, -1.0, 0) )

        # ── Iluminación ──
        # shadows=False es CRÍTICO para evitar Segmentation Fault en este entorno Linux.
        self.dir_light = DirectionalLight(color=color.rgb(255, 255, 255), y=5, z=-5, shadows=False)
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
        
        # [HOTFIX] Cegar temporalmente a la EditorCamera del input nativo de los Gamepads.
        # Esto soluciona el "drift" fantasma de los raw-nodes o mandos desconectados.
        _original_cam_update = self.cam.update
        def custom_cam_update():
            from ursina import held_keys
            # En lugar de iterar todos los keys, solo limpiamos los que usa EditorCamera
            # para evitar el lag de procesamiento por frame.
            keys_to_blind = [
                'gamepad left stick x', 'gamepad left stick y',
                'gamepad right stick x', 'gamepad right stick y',
                'gamepad left trigger', 'gamepad right trigger'
            ]
            backups = {}
            for k in keys_to_blind:
                if k in held_keys:
                    backups[k] = held_keys[k]
                    held_keys[k] = 0
            
            _original_cam_update()
            
            for k, v in backups.items():
                held_keys[k] = v
            
        self.cam.update = custom_cam_update
        
        # Networking (UDP receptor para no bloquear a la GUI principal)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permite reutilizar el puerto inmediatamente si se reinicia la app
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 5005))
        self.sock.setblocking(False)

        self.last_save_time = time.time()
        self.load_camera_config()
        
        self.spawned_objects = []
        
        # Instanciar el Gizmo Universal
        self.gizmo = TransformationGizmo()
        
        # ── Gestión de Spawn Relativo ──
        self.pending_spawn_data = None
        self.spawn_preview = None  # Se crea dinámicamente al activar el modo spawn
        
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

        # ── Collision System ──
        self.collision_mgr = CollisionManager(self, safety_margin=12.5)
        self.collision_interpolator = CollisionAwareInterpolator(self)

        # ── Gripper Physics Colliders (pinza1, pinza2, etc.) ──
        self.gripper_physics = []
        self._setup_gripper_colliders()

        scene.sim_instance = self

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
                    # Aplicar todos los ángulos recibidos en un solo bloque optimizado
                    self._apply_angles_batched(incoming)
                    
                    if not hasattr(self, "_last_link_log") or time.time() - self._last_link_log > 1.0:
                        print(f"[Link] Recibiendo ángulos: {incoming[0]:.1f}...")
                        self._last_link_log = time.time()
                    
                    # Forzar sincronización de vuelta con la GUI pero con límite de tasa (50Hz)
                    # para evitar que el tráfico UDP de vuelta ralentice el renderizado de Ursina
                    if not hasattr(self, "_last_sync_time") or time.time() - self._last_sync_time > 0.02:
                        self.sync_to_gui()
                        self._send_collision_status()
                        self._last_sync_time = time.time()
                elif msg.get("type") == "camera_offset":
                    data = msg.get("data", [0.0]*7)
                    x, y, z, zoom, pitch, roll, yaw = data
                    # EditorCamera offsets: local moves
                    if x or y or z:
                        self.cam.position += self.cam.right * x + self.cam.up * y + self.cam.forward * z
                    if zoom:
                        self.cam.position += self.cam.forward * zoom
                    if pitch or roll or yaw:
                        self.cam.rotation_x += pitch
                        self.cam.rotation_y += yaw
                        self.cam.rotation_z += roll
                elif msg.get("type") == "plan_path":
                    # GUI asks us to plan a collision-safe path
                    start = msg.get("start", list(self.angles))
                    end = msg.get("end", list(self.angles))
                    duration = msg.get("duration", 1.0)
                    waypoints, evasion_needed = self.collision_interpolator.plan_safe_path(start, end)
                    reply = json.dumps({
                        "type": "path_result",
                        "waypoints": waypoints,
                        "duration": duration,
                        "evasion": evasion_needed
                    })
                    try:
                        self.feedback_sock.sendto(reply.encode(), GUI_ADDR)
                    except Exception:
                        pass
                elif msg.get("type") == "spawn":
                    # En lugar de spawnear de inmediato, entramos en modo "espera de click"
                    self.pending_spawn_data = {
                        "shape": msg["shape"],
                        "size": msg["size"],
                        "mass": msg["mass"],
                        "model_path": msg.get("model_path")
                    }
                    # Crear preview blueprint del objeto
                    self._create_spawn_preview(
                        msg["shape"], msg["size"], msg.get("model_path")
                    )
                    print(f"Modo SPAWN activo para: {msg['shape']}")
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
                elif msg.get("type") == "load_svg":
                    path = msg.get("path")
                    self._load_svg_blueprint(path)
                elif msg.get("type") == "start_svg_trajectory":
                    self._start_cnc_execution()
                elif msg.get("type") == "stop_svg_trajectory":
                    self.cnc_active = False
                    self._send_cnc_status("stopped")
                    print("[CNC] Trayectoria detenida por el usuario.")
                elif msg.get("type") == "reset_cnc":
                    self._reset_cnc_trace()
                elif msg.get("type") == "set_cnc_params":
                    self.cnc_safety_height = msg.get("safety_height", 0.5)
                    if "feedrate" in msg:
                        self.cnc_feedrate = msg.get("feedrate", 1.5)
                    print(f"[CNC] Parámetros actualizados: Alt. Seguridad = {self.cnc_safety_height}, Velocidad = {getattr(self, 'cnc_feedrate', 1.5)}")
            except Exception as e:
                print("Error decodificando UDP:", e)

        # ── Ejecución de Trayectoria CNC ──
        if self.cnc_active and self.cnc_trajectory:
            self._update_cnc_execution()
        
        # ── Preview de Alcanzabilidad (solo en modo posicionamiento) ──
        if (not self.cnc_active and self.svg_blueprint 
                and self.gizmo.target == self.svg_blueprint):
            if not hasattr(self, '_reach_timer'):
                self._reach_timer = 0
            self._reach_timer += time.dt
            if self._reach_timer >= 0.2:
                self._reach_timer = 0
                self._update_blueprint_reachability()

        # ── Lógica de Spawn Relativo (Preview y Click) ──
        if self.pending_spawn_data and self.spawn_preview:
            # Mostrar preview solo si el ratón toca una superficie (suelo u objeto)
            if mouse.world_point:
                self.spawn_preview.enabled = True
                # Ajustar la altura según el tamaño del objeto para que no se entierre
                h = self.pending_spawn_data["size"] / 2
                self.spawn_preview.position = mouse.world_point + Vec3(0, h, 0)
                
                # Rotación lenta para efecto blueprint vivo
                self.spawn_preview.rotation_y += time.dt * 30
                
                # Click izquierdo para confirmar spawn
                if mouse.left:
                    spawn_pos = Vec3(self.spawn_preview.position)
                    self.spawn_object(
                        self.pending_spawn_data["shape"],
                        self.pending_spawn_data["size"],
                        self.pending_spawn_data["mass"],
                        position=spawn_pos,
                        model_path=self.pending_spawn_data.get("model_path")
                    )
                    print(f"Objeto spawneado en {spawn_pos}")
                    self._destroy_spawn_preview()
            else:
                self.spawn_preview.enabled = False
            
            # Click derecho o Escape para cancelar siempre (esté o no sobre superficie)
            if mouse.right or held_keys['escape']:
                self._destroy_spawn_preview()
                print("Spawn cancelado")
            
            return # Bloquear otras interacciones mientras se está en modo spawn

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

        # ── Update collision debug visuals ──
        self.collision_mgr.update_debug_visuals()
            
        # ── Limpiar objetos destruidos (Bullet maneja toda la física) ──
        self.spawned_objects = [
            o for o in self.spawned_objects
            if o and not getattr(o, 'destroyed', False)
        ]

    def input(self, key):
        if key == 'left mouse down':
            # Evitar solapamientos si estamos arrastrando el gizmo
            if self.gizmo.active_axis is not None:
                pass
            else:
                if mouse.hovered_entity:
                    # Gizmo sobre un objeto ya seleccionado
                    if isinstance(mouse.hovered_entity, Button) and getattr(mouse.hovered_entity, 'parent', None) in [self.gizmo.visuals_translate, self.gizmo.visuals_rotate, self.gizmo.visuals_scale]:
                        pass # El clic en el gizmo se procesa en el propio gizmo
                    else:
                        # Direct lookup via the back-reference we assigned in spawn_object
                        hovered = mouse.hovered_entity
                        clicked_phys = None
                        if hasattr(hovered, 'parent_physics'):
                            clicked_phys = hovered.parent_physics
                        elif hasattr(hovered, 'is_spawned_toy'):
                            clicked_phys = hovered
                        
                        if clicked_phys:
                            self.gizmo.attach_to(clicked_phys)
                            # SVG blueprints: ajustar escala del Gizmo y mostrar ejes
                            if getattr(clicked_phys, 'is_svg_blueprint', False):
                                extent = getattr(clicked_phys, 'mesh_extent', 1.0)
                                self.gizmo.world_scale = max(1.5, extent * 0.5)
                                self.gizmo.position = clicked_phys.position
                                # Mostrar ejes de traslación inmediatamente
                                self.gizmo.visuals_translate.enabled = True
                else:
                    # Deseleccionar al hacer clic en el vacío
                    self.gizmo.detach()
