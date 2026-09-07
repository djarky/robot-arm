import os
import socket
import json
import math
import time
import numpy as np
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
    JOINT_NAMES = ["J0", "J1","J2", "J3", "J4"]
    NUM_JOINTS = 5

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
        Entity(model='cube', color=color.red, scale=(5, 0.05, 0.05), position=(2.5, 0.05, 0))
        Entity(model='cube', color=color.green, scale=(0.05, 0.05, 5), position=(0, 0.05, 2.5))
        Entity(model='cube', color=color.blue, scale=(0.05, 5, 0.05), position=(0, 2.5, 0))

        # --- SVG/CNC State ---
        self.ik_solver = IK_Solver()
        self.svg_interpreter = SVGInterpreter(scale=0.02) # Escala original (1px = 0.02 unidades)
        self.svg_blueprint = None
        self.cnc_trajectory = [] # Lista de waypoints de mundo
        self.cnc_active = False
        self.cnc_index = 0
        self.cnc_feedrate = 1.5 # Unidades por segundo
        self.cnc_safety_height = 0.5 # Altura de levantamiento por defecto
        self.drawing_trace = Entity(model=Mesh(vertices=[], mode='line', thickness=3), color=color.green, always_on_top=True)
        self._trace_segments = []  # Lista de segmentos separados para el trazado
        
        # Láser de depuración visual (CNC Tip -> Target)
        self.debug_laser = Entity(model=Mesh(vertices=[Vec3(0,0,0), Vec3(0,0,0)], mode='line', thickness=5), color=color.red, always_on_top=True)
        self.debug_laser.visible = False

        # Root parent para mover todo el robot fácilmente (solicitud del usuario: moverlo más abajo)
        self.robot_root = Entity(position=(0, -1.0, 0) )

        # ── Iluminación ──
        self.dir_light = DirectionalLight(color=color.white, y=5, z=-5, shadows=False)
        self.dir_light.look_at(self.robot_root)
        self.ambient_light = AmbientLight(color=color.rgba(150/255, 150/255, 150/255, 0.6))
        
        # ── Cargar modelo GLB con armadura ──
        base_dir = os.path.dirname(os.path.dirname(__file__))
        model_path = os.path.join(base_dir, "robot_arm_sha.glb")
        
        # Cargamos el modelo GLB via gltf.load_model (bypassa el registro de Panda3D)
        from panda3d.core import NodePath
        model_root = NodePath(gltf.load_model(model_path))
        
        # IMPORTANTE: copy=False hace que el Actor "robe" el subárbol del Character
        # (J0_axis) directamente del model_root. Esto es necesario para que
        # controlJoint/exposeJoint funcionen sobre los nodos originales.
        self.actor = Actor(model_root, copy=False)
        
        # Contenedor Ursina para agrupar actor + partes estáticas del modelo
        self.actor_entity = Entity(parent=self.robot_root, texture='texture.png')
        
        # El Actor contiene SOLO el subárbol animado (lo que cuelga del Character
        # J0_axis): ejes, brazo, muñeca, garra, etc.
        self.actor.reparentTo(self.actor_entity)
        self.actor.setScale(1)
        self.actor.setPos(0, 0, 0)
        
        # model_root contiene las partes ESTÁTICAS que el Actor no incluyó:
        # concretamente BASE/pata4 (la base fija del robot). Sin esta línea,
        # la base del robot es INVISIBLE.
        model_root.reparentTo(self.actor_entity)
        
        # --- GARRA (Gripper) ---
        claw_anchor = self.actor.find("**/base-de-la-garra-parent")
        if not claw_anchor.isEmpty():
            # Forzar visibilidad de toda la cadena de la garra
            claw_anchor.show()
            for child in claw_anchor.findAllMatches("**"):
                child.show()
            print("[RobotSim] Garra detectada — posicionada por esqueleto (CharacterJointEffect → J4).")
        else:
            print("[RobotSim] Advertencia: base-de-la-garra-parent no encontrado.")

        # --- Punto de Referencia CNC para IK ---
        # Usamos J4 como referencia ya que J5 está vacío
        j4_bone = self.actor.exposeJoint(None, "modelRoot", "J4")
        self.cnc_node = self.actor.find("**/CNC") # Guardar referencia para actualizaciones dinámicas
        
        if not self.cnc_node.isEmpty() and not j4_bone.isEmpty():
            # Obtener vector 3D J4 -> CNC
            offset_vec = self.cnc_node.getPos(j4_bone)
            # Panda3D (X, Y, Z) -> Ursina/IK (X, Y, Z) 
            # Panda3D: X=lateral, Y=forward, Z=up
            # Ursina/IK: X=lateral, Y=up, Z=forward
            # Mapping: IK.x = Panda.x, IK.y = Panda.z, IK.z = Panda.y
            self.ik_solver.TOOL_OFFSET = np.array([offset_vec.x, offset_vec.z, offset_vec.y])
            self.ik_solver.L_TOOL = np.linalg.norm(self.ik_solver.TOOL_OFFSET)
            print(f"[IK] Herramienta Calibrada (J4→CNC): Panda3D_raw=({offset_vec.x:.4f}, {offset_vec.y:.4f}, {offset_vec.z:.4f}) -> IK_Offset={self.ik_solver.TOOL_OFFSET}, L={self.ik_solver.L_TOOL:.4f}")
        
        # --- Configurar Actores de la Garra (Animación) ---
        self._setup_gripper_actors(model_path)

        # --- Calibración Dinámica de Segmentos para IK ---
        # 1. D1: Altura desde la base (modelRoot) hasta el hombro (J1)
        j1_bone = self.actor.exposeJoint(None, "modelRoot", "J1")
        if not j1_bone.isEmpty():
            self.ik_solver.D1 = j1_bone.getPos(model_root).z 
            print(f"[IK] D1 (Base→Hombro): {self.ik_solver.D1:.4f}")
            
        # 2. L1: Longitud del brazo (J1 → J2)
        j2_bone = self.actor.exposeJoint(None, "modelRoot", "J2")
        if not j1_bone.isEmpty() and not j2_bone.isEmpty():
            self.ik_solver.L1 = j2_bone.getPos(j1_bone).length()
            print(f"[IK] L1 (Hombro→Codo): {self.ik_solver.L1:.4f}")
            
        # 3. L2: Longitud del antebrazo (J2 → J4)
        if not j2_bone.isEmpty() and not j4_bone.isEmpty():
            self.ik_solver.L2 = j4_bone.getPos(j2_bone).length()
            print(f"[IK] L2 (Codo→Muñeca): {self.ik_solver.L2:.4f}")

        # --- Obtener nodos controlables para cada junta ---
        self.joint_controls = {}
        self.rest_hprs = {}
        pnames = self.actor.getPartNames()
        primary_part = pnames[0] if pnames else "modelRoot"
        
        for jname in self.JOINT_NAMES:
            try:
                ctrl = self.actor.controlJoint(None, primary_part, jname)
                self.joint_controls[jname] = ctrl
                self.rest_hprs[jname] = ctrl.getHpr()
                print(f"  controlJoint('{jname}') → OK | Rest HPR: {self.rest_hprs[jname]}")
            except Exception as e:
                print(f"  controlJoint('{jname}') → FALLO en parte '{primary_part}': {e}")

        # Eje de rotación por junta
        self.joint_axes = {
            "J0": "YAW", "J1": "ROLL", "J2": "ROLL", "J3": "YAW", "J4": "PITCH",
        }

        self.angles = [0] * self.NUM_JOINTS
        
        # Configuración de Cámara
        self.cam = EditorCamera()
        self.cam.position = (0, 3, -8)
        self.cam.look_at(self.floor)
        
        # Blinder para gamepad en cámara
        _original_cam_update = self.cam.update
        def custom_cam_update():
            from ursina import held_keys
            keys_to_blind = ['gamepad left stick x', 'gamepad left stick y', 'gamepad right stick x', 'gamepad right stick y']
            backups = {k: held_keys[k] for k in keys_to_blind if k in held_keys}
            for k in backups: held_keys[k] = 0
            _original_cam_update()
            for k, v in backups.items(): held_keys[k] = v
        self.cam.update = custom_cam_update
        
        # Networking
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 5005))
        self.sock.setblocking(False)

        self.last_save_time = time.time()
        self.load_camera_config()
        self.spawned_objects = []
        self.gizmo = TransformationGizmo()
        self.pending_spawn_data = None
        self.spawn_preview = None
        
        # Sliders Circulares
        self.joint_sliders = []
        for i, jname in enumerate(self.JOINT_NAMES):
            ctrl = self.joint_controls.get(jname)
            if ctrl:
                axis = self.joint_axes[jname]
                slider = CircularJointSlider(self, i, axis=axis, radius=1.0) 
                exposed_node = self.actor.exposeJoint(None, "modelRoot", jname)
                slider.parent = exposed_node
                slider.position = (0,0,0)
                slider.world_scale = 12.0 
                self.joint_sliders.append(slider)

        self.collision_mgr = CollisionManager(self, safety_margin=1.25)
        self.collision_interpolator = CollisionAwareInterpolator(self)
        self.gripper_physics = []
        self._setup_gripper_colliders()
        scene.sim_instance = self

    def recalibrate_tool(self):
        """Mide la posición actual del nodo CNC respecto a la muñeca (J4)."""
        j4_bone = self.actor.exposeJoint(None, "modelRoot", "J4")
        if not hasattr(self, 'cnc_node') or self.cnc_node.isEmpty() or j4_bone.isEmpty():
            return
            
        offset_vec = self.cnc_node.getPos(j4_bone)
        # Panda3D (X, Y, Z) -> Ursina/IK (X, Y, Z)
        # Panda3D: X=lateral, Y=forward, Z=up
        # Ursina/IK: X=lateral, Y=up, Z=forward
        self.ik_solver.TOOL_OFFSET = np.array([offset_vec.x, offset_vec.z, offset_vec.y])
        self.ik_solver.L_TOOL = np.linalg.norm(self.ik_solver.TOOL_OFFSET)
        print(f"[IK] Re-calibración: Offset={self.ik_solver.TOOL_OFFSET}, L={self.ik_solver.L_TOOL:.4f}")

    def update(self):
        # Recibir mensajes de control de la GUI principal.
        data_received = False
        last_data = None
        while True:
            try:
                data, _ = self.sock.recvfrom(1024)
                last_data = data
                data_received = True
            except BlockingIOError:
                break 

        if data_received and last_data:
            try:
                msg = json.loads(last_data.decode())
                if msg.get("type") == "angles":
                    incoming = msg["data"]
                    self._apply_angles_batched(incoming)
                    if not hasattr(self, "_last_sync_time") or time.time() - self._last_sync_time > 0.02:
                        self.sync_to_gui()
                        self._last_sync_time = time.time()
                elif msg.get("type") == "camera_offset":
                    data = msg.get("data", [0.0]*7)
                    x, y, z, zoom, pitch, roll, yaw = data
                    if x or y or z: self.cam.position += self.cam.right * x + self.cam.up * y + self.cam.forward * z
                    if zoom: self.cam.position += self.cam.forward * zoom
                    if pitch or roll or yaw:
                        self.cam.rotation_x += pitch
                        self.cam.rotation_y += yaw
                        self.cam.rotation_z += roll
                elif msg.get("type") == "plan_path":
                    start = msg.get("start", list(self.angles))
                    end = msg.get("end", list(self.angles))
                    duration = msg.get("duration", 1.0)
                    waypoints, evasion_needed = self.collision_interpolator.plan_safe_path(start, end)
                    reply = json.dumps({"type": "path_result", "waypoints": waypoints, "duration": duration, "evasion": evasion_needed})
                    self.feedback_sock.sendto(reply.encode(), GUI_ADDR)
                elif msg.get("type") == "spawn":
                    self.pending_spawn_data = {"shape": msg["shape"], "size": msg["size"], "mass": msg["mass"], "model_path": msg.get("model_path")}
                    self._create_spawn_preview(msg["shape"], msg["size"], msg.get("model_path"))
                elif msg.get("type") == "reset_camera":
                    self.load_camera_config(reset=True)
                elif msg.get("type") == "screenshot":
                    path = msg.get("path", "pose_thumb.png")
                    from panda3d.core import Filename
                    try:
                        parent_dir = os.path.dirname(path)
                        if parent_dir and not os.path.exists(parent_dir): os.makedirs(parent_dir)
                        fn = Filename.fromOsSpecific(path)
                        base.win.saveScreenshot(fn)
                    except Exception as e: print(f"Error screenshot: {e}")
                elif msg.get("type") == "load_svg":
                    self._load_svg_blueprint(msg.get("path"))
                elif msg.get("type") == "start_svg_trajectory":
                    self._start_cnc_execution()
                elif msg.get("type") == "stop_svg_trajectory":
                    self.cnc_active = False
                    self._send_cnc_status("stopped")
                elif msg.get("type") == "reset_cnc":
                    self._reset_cnc_trace()
                elif msg.get("type") == "set_cnc_params":
                    self.cnc_safety_height = msg.get("safety_height", 0.5)
                    if "feedrate" in msg: self.cnc_feedrate = msg.get("feedrate", 1.5)
                elif msg.get("type") == "gripper":
                    self.set_gripper_state(float(msg.get("data", 0.0)))
            except Exception as e:
                print("Error UDP:", e)

        if self.cnc_active and self.cnc_trajectory:
            self._update_cnc_execution()
        
        if (not self.cnc_active and self.svg_blueprint and self.gizmo.target == self.svg_blueprint):
            if not hasattr(self, '_reach_timer'): self._reach_timer = 0
            self._reach_timer += time.dt
            if self._reach_timer >= 1.0:  # Virtual trace is heavier, run less frequently
                self._reach_timer = 0
                self._update_blueprint_reachability()

        if self.pending_spawn_data and self.spawn_preview:
            if mouse.world_point:
                self.spawn_preview.enabled = True
                h = self.pending_spawn_data["size"] / 2
                self.spawn_preview.position = mouse.world_point + Vec3(0, h, 0)
                self.spawn_preview.rotation_y += time.dt * 30
                if mouse.left:
                    self.spawn_object(self.pending_spawn_data["shape"], self.pending_spawn_data["size"], self.pending_spawn_data["mass"], position=Vec3(self.spawn_preview.position), model_path=self.pending_spawn_data.get("model_path"))
                    self._destroy_spawn_preview()
            else:
                self.spawn_preview.enabled = False
            if mouse.right or held_keys['escape']:
                self._destroy_spawn_preview()
            return 

        if held_keys['shift']:
            if mouse.left:
                self._apply_angle(0, self._get_angle(0) + mouse.velocity[0] * 100)
                self._apply_angle(1, self._get_angle(1) - mouse.velocity[1] * 100)
            elif mouse.right:
                self._apply_angle(2, self._get_angle(2) - mouse.velocity[1] * 100)
            self.sync_to_gui()
        
        if time.time() - self.last_save_time > 5:
            self.save_camera_config()
            self.last_save_time = time.time()

        # ── Actualizar Láser de Depuración ──
        # Mostrar si hay una trayectoria activa O si hay un blueprint cargado (apuntando al primer punto)
        show_laser = False
        target_pos = Vec3(0,0,0)
        
        if getattr(self, 'cnc_active', False):
            show_laser = True
            target_pos = getattr(self, 'cnc_logical_pos', Vec3(0,0,0))
        elif self.svg_blueprint and getattr(self, 'cnc_trajectory', []):
            show_laser = True
            # Point to the center of the blueprint before execution
            target_pos = self.svg_blueprint.world_position
            
        if show_laser and hasattr(self, 'cnc_node') and not self.cnc_node.isEmpty():
            self.debug_laser.visible = True
            # Panda3D native call for world position
            tip_pos = Vec3(self.cnc_node.getPos(base.render))
            
            # Actualizar malla
            self.debug_laser.model.vertices = [tip_pos, target_pos]
            self.debug_laser.model.generate()
            
            dist = (tip_pos - target_pos).length()
            self.debug_laser.color = color.green if dist < 0.05 else color.red
        else:
            if hasattr(self, 'debug_laser'):
                self.debug_laser.visible = False

        self.collision_mgr.update_debug_visuals()
        self.spawned_objects = [o for o in self.spawned_objects if o and not getattr(o, 'destroyed', False)]

    def input(self, key):
        if key == 'left mouse down':
            if self.gizmo.active_axis is None:
                if mouse.hovered_entity:
                    if isinstance(mouse.hovered_entity, Button) and getattr(mouse.hovered_entity, 'parent', None) in [self.gizmo.visuals_translate, self.gizmo.visuals_rotate, self.gizmo.visuals_scale]:
                        pass 
                    else:
                        hovered = mouse.hovered_entity
                        clicked_phys = getattr(hovered, 'parent_physics', None) or (hovered if hasattr(hovered, 'is_spawned_toy') else None)
                        if clicked_phys:
                            self.gizmo.attach_to(clicked_phys)
                            if getattr(clicked_phys, 'is_svg_blueprint', False):
                                extent = getattr(clicked_phys, 'mesh_extent', 1.0)
                                self.gizmo.world_scale = max(1.5, extent * 0.5)
                                self.gizmo.position = clicked_phys.position
                                self.gizmo.visuals_translate.enabled = True
                else:
                    self.gizmo.detach()
