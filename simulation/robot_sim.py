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


# ── Bullet Collider Helpers ──────────────────────────────────────────

def ConvexHullCollider(entity_model):
    """Genera BulletConvexHullShape a partir de los vértices reales del mesh.
    Se ajusta fielmente a la geometría — no es un AABB ni una caja."""
    shape = BulletConvexHullShape()
    geom_nodes = entity_model.findAllMatches('**/+GeomNode')
    for geom_np in geom_nodes:
        geom_node = geom_np.node()
        for i in range(geom_node.getNumGeoms()):
            shape.addGeom(geom_node.getGeom(i))
    return shape


def TorusCompoundCollider(entity_model, num_segments=8):
    """Genera N ConvexHulls segmentados para preservar el agujero del torus.
    Los objetos pueden pasar por el centro de la dona.
    Retorna lista de BulletConvexHullShape para addShape al RigidBodyNode."""
    shapes = []
    geom_nodes = entity_model.findAllMatches('**/+GeomNode')
    if geom_nodes.getNumPaths() == 0:
        return shapes

    # Collect ALL vertices from all geoms
    vertices = []
    for gn_np in geom_nodes:
        geom_node = gn_np.node()
        for gi in range(geom_node.getNumGeoms()):
            geom = geom_node.getGeom(gi)
            vdata = geom.getVertexData()
            reader = GeomVertexReader(vdata, 'vertex')
            while not reader.isAtEnd():
                v = reader.getData3f()
                vertices.append((v.x, v.y, v.z))

    if len(vertices) < 4:
        return shapes

    # Divide vertices into angular segments (by angle in the XZ plane)
    segment_verts = [[] for _ in range(num_segments)]
    for vx, vy, vz in vertices:
        angle = math.atan2(vz, vx)  # -pi to pi
        angle_norm = (angle + math.pi) / (2 * math.pi)  # 0 to 1
        seg_idx = int(angle_norm * num_segments) % num_segments
        # Add to this segment AND the next for overlap/continuity
        segment_verts[seg_idx].append(LPoint3f(vx, vy, vz))
        next_idx = (seg_idx + 1) % num_segments
        segment_verts[next_idx].append(LPoint3f(vx, vy, vz))

    for seg in segment_verts:
        if len(seg) < 4:
            continue
        hull = BulletConvexHullShape()
        for pt in seg:
            hull.addPoint(pt)
        shapes.append(hull)

    return shapes

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

    def _apply_angle_raw(self, joint_index, angle_deg):
        """Apply angle WITHOUT collision check.  Used internally by
        the collision system for tentative testing."""
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

    def _apply_angle(self, joint_index, angle_deg, force=False):
        """Apply angle with smart collision check.  Returns True if accepted.

        Uses 'would_worsen' logic: if the arm is already near/in collision
        with the floor, movements that RAISE the arm (improve the situation)
        are still allowed.  Only movements that push the arm LOWER are blocked.
        This prevents the 'total lockout' bug where the arm gets stuck.
        """
        if force or not hasattr(self, 'collision_mgr'):
            self._apply_angle_raw(joint_index, angle_deg)
            return True

        # Snapshot the lowest probe Y BEFORE the change
        old_min_y = self.collision_mgr.get_min_probe_y()
        old_angle = self.angles[joint_index]

        # Apply tentatively
        self._apply_angle_raw(joint_index, angle_deg)

        # Check if this made things worse
        if self.collision_mgr.would_worsen(old_min_y):
            # Revert
            self._apply_angle_raw(joint_index, old_angle)
            return False
        return True

    def _apply_angles_batched(self, angles_list, force=False):
        """Apply a list of angles all at once with a single collision check.

        This is much faster than calling _apply_angle joint by joint because
        it only forces a Panda3D skeleton update once before and once after
        the entire batch of changes.
        """
        num_to_apply = min(len(angles_list), self.NUM_JOINTS)
        if force or not hasattr(self, 'collision_mgr'):
            for i in range(num_to_apply):
                self._apply_angle_raw(i, angles_list[i])
            return True

        # 1. Snapshot state BEFORE
        # Force update ONCE to get accurate starting position
        old_min_y = self.collision_mgr.get_min_probe_y(force_update=True)
        old_angles = list(self.angles)

        # 2. Apply ALL angles raw (fast, no physics update)
        for i in range(num_to_apply):
            self._apply_angle_raw(i, angles_list[i])

        # 3. Check if the TOTAL change made things worse
        # would_worsen calls get_min_probe_y(force_update=True) internally
        if self.collision_mgr.would_worsen(old_min_y):
            # Revert ALL if blocked
            for i, old_a in enumerate(old_angles):
                self._apply_angle_raw(i, old_a)
            return False

        return True

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

    def _setup_gripper_colliders(self):
        """Configura colliders BulletTriangleMeshShape para las pinzas del robot.
        Usa la geometría exacta (cada triángulo) del mesh real del modelo GLB.
        Son kinematic: el usuario las mueve via joints, Bullet las usa para
        empujar objetos spawneados."""
        gripper_parts = [
            'pinza1', 'pinza2', 'base-de-la-garra', 'tapa-garra',
            'engranaje1', 'engranaje2', 'barra1', 'barra2'
        ]

        for part_name in gripper_parts:
            try:
                results = self.actor.findAllMatches(f'**/{part_name}')
                if results.getNumPaths() == 0:
                    print(f"[Gripper] Parte '{part_name}' no encontrada")
                    continue

                part_np = results.getPath(0)

                # Find GeomNodes — either the node itself or its children
                geom_nps = part_np.findAllMatches('**/+GeomNode')
                if geom_nps.getNumPaths() == 0:
                    # The node itself may be a GeomNode
                    if part_np.node().getType().getName() == 'GeomNode':
                        geom_nps = [part_np]
                    else:
                        print(f"[Gripper] '{part_name}' sin GeomNodes")
                        continue

                # Build BulletTriangleMesh from exact geometry
                bullet_mesh = BulletTriangleMesh()
                found_geoms = False
                for gn_np in geom_nps:
                    gn = gn_np.node() if hasattr(gn_np, 'node') else gn_np
                    for gi in range(gn.getNumGeoms()):
                        bullet_mesh.addGeom(gn.getGeom(gi))
                        found_geoms = True

                if not found_geoms:
                    print(f"[Gripper] '{part_name}' sin geometría")
                    continue

                mesh_shape = BulletTriangleMeshShape(bullet_mesh, dynamic=False)

                # Create kinematic RigidBodyNode
                rb_node = BulletRigidBodyNode(f'gripper_{part_name}')
                rb_node.addShape(mesh_shape)
                rb_node.setMass(0)
                rb_node.setKinematic(True)

                # Parent to the actor part so it follows skeleton animation
                rb_np = part_np.attachNewNode(rb_node)
                physics_handler.world.attachRigidBody(rb_node)

                self.gripper_physics.append(rb_np)
                print(f"[Gripper] ✓ Collider mesh exacto para '{part_name}'")
            except Exception as e:
                print(f"[Gripper] Error configurando '{part_name}': {e}")

    # ------------------------------------------------------------------
    # Spawn Preview (Blueprint)
    # ------------------------------------------------------------------

    BLUEPRINT_COLOR = color.rgba(0, 0.7, 1, 0.25)  # Cian semi-transparente

    def _create_spawn_preview(self, shape, size, model_path=None):
        """Crea un preview 'blueprint' del objeto a spawnear.
        Muestra la forma real con apariencia holográfica."""
        # Limpiar preview anterior (solo la entidad, NO el pending_spawn_data)
        if self.spawn_preview:
            destroy(self.spawn_preview)
            self.spawn_preview = None

        preview_model = None

        if shape == "cube":
            preview_model = 'cube'
        elif shape == "sphere":
            preview_model = 'sphere'
        elif shape == "cylinder":
            preview_model = Cylinder(resolution=16)
        elif shape == "torus":
            torus_path = [Vec3(math.cos(math.radians(i * (360 / 30))), 0,
                         math.sin(math.radians(i * (360 / 30)))) for i in range(31)]
            cross_section = [Vec3(math.cos(math.radians(i * (360 / 8))) * 0.2,
                            math.sin(math.radians(i * (360 / 8))) * 0.2, 0) for i in range(9)]
            try:
                preview_model = Pipe(path=torus_path, base_shape=cross_section, cap_ends=False)
            except Exception:
                preview_model = 'sphere'
        elif shape == "custom" and model_path:
            # Intentar cargar el modelo GLB para el preview
            ext = os.path.splitext(model_path)[1].lower()
            if ext in ('.glb', '.gltf'):
                try:
                    panda_node = gltf.load_model(model_path)
                    loaded_np = NodePath(panda_node)

                    # Crear entity contenedor
                    self.spawn_preview = Entity(
                        scale=size,
                        color=self.BLUEPRINT_COLOR,
                        enabled=False,
                        always_on_top=True,
                        unlit=True
                    )
                    # Normalizar el modelo (misma lógica que spawn_object)
                    bounds = loaded_np.getTightBounds()
                    if bounds:
                        min_p, max_p = bounds
                        extent = max(
                            max_p.getX() - min_p.getX(),
                            max_p.getY() - min_p.getY(),
                            max_p.getZ() - min_p.getZ()
                        )
                        if extent > 0:
                            norm_scale = 1.0 / extent
                            loaded_np.setScale(norm_scale)
                            cx = (min_p.getX() + max_p.getX()) / 2.0
                            cy = (min_p.getY() + max_p.getY()) / 2.0
                            cz = (min_p.getZ() + max_p.getZ()) / 2.0
                            loaded_np.setPos(-cx * norm_scale, -cy * norm_scale, -cz * norm_scale)

                    loaded_np.reparentTo(self.spawn_preview)
                    # Aplicar color blueprint a todos los geom nodes
                    loaded_np.setColorScale(0, 0.7, 1, 0.25)
                    loaded_np.setTransparency(True)

                    self.spawn_preview.collider = None
                    print(f"[Preview] GLB preview creado para: {model_path}")
                    return
                except Exception as e:
                    print(f"[Preview] Error cargando GLB preview, usando cubo: {e}")
                    preview_model = 'cube'
            else:
                preview_model = 'cube'
        else:
            preview_model = 'cube'

        # Crear preview con forma estándar
        self.spawn_preview = Entity(
            model=preview_model,
            scale=size,
            color=self.BLUEPRINT_COLOR,
            enabled=False,
            always_on_top=True,
            unlit=True
        )
        self.spawn_preview.collider = None
        print(f"[Preview] Blueprint preview creado: {shape} (size={size})")

    def _destroy_spawn_preview(self):
        """Destruye el preview de spawn y limpia el estado."""
        if self.spawn_preview:
            destroy(self.spawn_preview)
            self.spawn_preview = None
        self.pending_spawn_data = None

    def spawn_object(self, shape, size, mass, position=None, model_path=None):
        """Spawnea objetos con físicas Bullet reales.
        Cada objeto usa el collider que corresponde EXACTAMENTE a su geometría."""
        spawn_pos = position if position else (2.5, 3, 0)
        obj = None

        if shape == "cube":
            # BulletBoxShape IS the exact shape of a cube
            obj = PhysicsEntity(
                model='cube', scale=size, color=color.random_color(),
                position=spawn_pos, collider='box',
                mass=mass, friction=0.7
            )

        elif shape == "sphere":
            # BulletSphereShape IS the exact shape of a sphere — rolls naturally
            obj = PhysicsEntity(
                model='sphere', scale=size, color=color.random_color(),
                position=spawn_pos, collider='sphere',
                mass=mass, friction=0.5
            )
        elif shape == "cylinder":
            # ConvexHullShape from the real cylinder vertices — rolls naturally
            cyl_model = Cylinder(resolution=16)
            obj = PhysicsEntity(
                model=cyl_model, scale=size, color=color.random_color(),
                position=spawn_pos, mass=mass, friction=0.5
            )
            try:
                hull = ConvexHullCollider(obj.entity.model)
                obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Cylinder hull fallback: {e}")
                obj.collider = 'box'
        elif shape == "torus":
            # CompoundShape of N segmented ConvexHulls — hole is traversable
            torus_path = [Vec3(math.cos(math.radians(i * (360 / 30))), 0,
                         math.sin(math.radians(i * (360 / 30)))) for i in range(31)]
            cross_section = [Vec3(math.cos(math.radians(i * (360 / 8))) * 0.2,
                            math.sin(math.radians(i * (360 / 8))) * 0.2, 0) for i in range(9)]
            try:
                torus_model = Pipe(path=torus_path, base_shape=cross_section, cap_ends=False)
                torus_model.generate_normals()
                torus_model.smooth = True
                obj = PhysicsEntity(
                    model=torus_model, scale=size, color=color.random_color(),
                    position=spawn_pos, mass=mass, friction=0.5
                )
                hulls = TorusCompoundCollider(obj.entity.model, num_segments=8)
                for hull_shape in hulls:
                    obj.node.addShape(hull_shape)
                if not hulls:
                    print("[Spawn] Torus: no hull segments, using convex hull")
                    hull = ConvexHullCollider(obj.entity.model)
                    obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Torus error: {e}")
                obj = PhysicsEntity(
                    model='sphere', scale=(size, size * 0.5, size),
                    color=color.random_color(), position=spawn_pos,
                    collider='sphere', mass=mass, friction=0.5
                )
        elif shape == "custom" and model_path:
            try:
                ext = os.path.splitext(model_path)[1].lower()
                loaded_np = None

                if ext in ('.glb', '.gltf'):
                    # Usar gltf.load_model — misma técnica probada del brazo robótico
                    panda_node = gltf.load_model(model_path)
                    loaded_np = NodePath(panda_node)
                    print(f"[Spawn] Modelo GLB cargado: {model_path}")

                if loaded_np:
                    # ── Normalizar geometría para que quepa en un cubo unitario ──
                    # Esto es CRÍTICO para que el picker, gizmo y collider funcionen
                    # correctamente con el parámetro 'size'.
                    bounds = loaded_np.getTightBounds()
                    if bounds:
                        min_p, max_p = bounds
                        extent = max(
                            max_p.getX() - min_p.getX(),
                            max_p.getY() - min_p.getY(),
                            max_p.getZ() - min_p.getZ()
                        )
                        if extent > 0:
                            norm_scale = 1.0 / extent
                            loaded_np.setScale(norm_scale)
                            # Centrar el modelo en el origen del entity
                            center_x = (min_p.getX() + max_p.getX()) / 2.0
                            center_y = (min_p.getY() + max_p.getY()) / 2.0
                            center_z = (min_p.getZ() + max_p.getZ()) / 2.0
                            loaded_np.setPos(
                                -center_x * norm_scale,
                                -center_y * norm_scale,
                                -center_z * norm_scale
                            )
                            print(f"[Spawn] Modelo normalizado: extent={extent:.1f} → scale={norm_scale:.4f}")
                        else:
                            loaded_np.setScale(1)
                    else:
                        loaded_np.setScale(1)
                        print("[Spawn] WARN: No se pudieron calcular bounds, usando scale=1")

                    # Crear PhysicsEntity con box collider (el modelo está normalizado
                    # a un cubo unitario, así que 'box' es una aproximación correcta)
                    obj = PhysicsEntity(
                        model='cube', scale=size, color=color.white,
                        position=spawn_pos, collider='box',
                        mass=mass, friction=0.5
                    )
                    # Ocultar la geometría del cubo dummy usando stash
                    # (hide() puede causar problemas de herencia visual)
                    cube_geoms = obj.entity.findAllMatches('**/+GeomNode')
                    for g in cube_geoms:
                        g.stash()

                    # Reparentar el modelo normalizado al entity visual
                    loaded_np.reparentTo(obj.entity)
                    # Bloquear la herencia de color del padre para que los
                    # materiales originales del GLB se mantengan intactos
                    loaded_np.setColorScaleOff()
                    # El box collider del PhysicsEntity es suficiente ya que el modelo
                    # está normalizado a un cubo unitario. Los modelos GLB complejos
                    # pueden tener 100k+ vértices, lo cual congela la simulación
                    # si intentamos construir un ConvexHull vértice a vértice.
                    print(f"[Spawn] Modelo custom spawneado con box collider")
                else:
                    # Para OBJ y otros formatos, intentar carga directa de Ursina
                    obj = PhysicsEntity(
                        model=model_path, scale=size, color=color.random_color(),
                        position=spawn_pos, mass=mass, friction=0.5
                    )
                    hull = ConvexHullCollider(obj.entity.model)
                    obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Error cargando modelo custom ({model_path}): {e}")
                import traceback
                traceback.print_exc()
                # Fallback a cubo si falla
                obj = PhysicsEntity(
                    model='cube', scale=size, color=color.random_color(),
                    position=spawn_pos, collider='box',
                    mass=mass, friction=0.7
                )

        if obj:
            obj.is_spawned_toy = True
            if hasattr(obj, 'entity'):
                # Proxy invisible estricto que Ursina siempre detectará en sus raycasts normales
                picker = Entity(parent=obj.entity, model='cube', scale=1, collider='box', color=color.clear)
                picker.is_spawned_toy = True
                picker.parent_physics = obj
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
                    print(f"[CNC] Parámetros actualizados: Alt. Seguridad = {self.cnc_safety_height}")
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

    def _load_svg_blueprint(self, path):
        """Carga el SVG y crea una representación visual (holograma)."""
        if self.svg_blueprint:
            if self.svg_blueprint in self.spawned_objects:
                self.spawned_objects.remove(self.svg_blueprint)
            destroy(self.svg_blueprint)
            self.svg_blueprint = None
        
        raw_paths = self.svg_interpreter.parse_file(path)
        if not raw_paths:
            print(f"[CNC] Error: No se encontraron rutas en {path}")
            return
        
        # ── Paso 1: Generar vértices crudos y calcular bounding box ──
        raw_verts = []
        min_x, max_x = float('inf'), float('-inf')
        min_z, max_z = float('inf'), float('-inf')
        
        for svg_path in raw_paths:
            for i in range(len(svg_path)-1):
                x1 = svg_path[i]['pos'][0] * self.svg_interpreter.scale
                z1 = svg_path[i]['pos'][1] * self.svg_interpreter.scale
                x2 = svg_path[i+1]['pos'][0] * self.svg_interpreter.scale
                z2 = svg_path[i+1]['pos'][1] * self.svg_interpreter.scale
                raw_verts.append((x1, z1))
                raw_verts.append((x2, z2))
                min_x = min(min_x, x1, x2)
                max_x = max(max_x, x1, x2)
                min_z = min(min_z, z1, z2)
                max_z = max(max_z, z1, z2)
        
        if not raw_verts:
            print("[CNC] Error: SVG no generó vértices.")
            return
        
        # ── Paso 2: Centrar vértices en el origen local ──
        cx = (min_x + max_x) / 2
        cz = (min_z + max_z) / 2
        centered_verts = [(x - cx, 0, z - cz) for x, z in raw_verts]
        
        w = max(max_x - min_x, 0.2)
        d = max(max_z - min_z, 0.2)
        extent = max(w, d)
        
        # ── Paso 3: Crear entidad con mesh centrado y vertex colors ──
        # La posición del Entity ES el centro del dibujo.
        initial_colors = [color.rgba(0, 200, 255, 180)] * len(centered_verts)  # Cyan por defecto
        self.svg_blueprint = Entity(
            model=Mesh(vertices=centered_verts, colors=initial_colors, mode='line', thickness=3),
            color=color.white,  # Blanco para que vertex colors se vean sin tinte
            position=(2, 0.05, 0),
            always_on_top=True,
            unlit=True
        )
        self.svg_blueprint.raw_paths = raw_paths
        self.svg_blueprint.is_svg_blueprint = True
        self.svg_blueprint.mesh_extent = extent
        self.svg_blueprint.mesh_offset_raw = (cx, cz)
        self.svg_blueprint.vert_count = len(centered_verts)
        
        # ── Mapeo de segmentos a waypoints ──
        # Cada par de vértices (2*s, 2*s+1) corresponde al segmento entre waypoint[i] y waypoint[i+1]
        # Almacenar el índice del waypoint FINAL de cada segmento en la trayectoria plana
        seg_wp_end = []  # Para cada segmento s, el índice plano del waypoint final
        flat_idx = 0
        for svg_path in raw_paths:
            for i in range(len(svg_path) - 1):
                seg_wp_end.append(flat_idx + i + 1)
            flat_idx += len(svg_path)
        self.svg_blueprint.seg_wp_end = seg_wp_end
        
        # ── Paso 4: Picker centrado en (0,0,0) local ──
        picker = Entity(
            parent=self.svg_blueprint,
            model='cube',
            color=color.rgba(0, 0.7, 1, 0.08),
            position=(0, 0, 0),
            scale=(w, 0.15, d),
            collider='box'
        )
        picker.is_spawned_toy = True
        picker.parent_physics = self.svg_blueprint
        
        self.svg_blueprint.is_spawned_toy = True 
        self.spawned_objects.append(self.svg_blueprint)
        
        self._send_cnc_status("loaded")
        print(f"[CNC] Blueprint cargado: {path} ({len(centered_verts)//2} segmentos, {len(seg_wp_end)} trazos, extent={extent:.1f})")


    def _start_cnc_execution(self):
        """Prepara los waypoints de mundo directamente desde las coordenadas del mesh,
        garantizando que coincidan con la posición visual del blueprint."""
        if not self.svg_blueprint:
            print("[CNC] Error: No hay SVG cargado.")
            self._send_cnc_status("error", "No hay SVG cargado")
            return
        
        bp = self.svg_blueprint
        raw_paths = bp.raw_paths
        
        # Offset usado para centrar el mesh (calculado en _load_svg_blueprint)
        cx, cz = getattr(bp, 'mesh_offset_raw', (0, 0))
        scale_factor = self.svg_interpreter.scale  # 0.02 (px → mundo)
        
        # Transformación REAL de la entidad (world_position incluye jerarquía de padres)
        entity_pos = bp.world_position
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        print(f"[CNC] Blueprint transform: pos={entity_pos}, scale={entity_scale}, rot_y={entity_rot_y}")
        print(f"[CNC] Mesh offset: cx={cx:.4f}, cz={cz:.4f}, svg_scale={scale_factor}")
        
        self.cnc_trajectory = []
        
        for path in raw_paths:
            for wp in path:
                # 1. Coordenada local del mesh (misma fórmula que _load_svg_blueprint)
                local_x = wp['pos'][0] * scale_factor - cx
                local_z = wp['pos'][1] * scale_factor - cz
                
                # 2. Aplicar escala de la entidad (Ursina: mesh_vertex * entity.scale)
                scaled_x = local_x * entity_scale.x
                scaled_z = local_z * entity_scale.z
                
                # 3. Aplicar rotación Y (en plano XZ)
                rot_x = scaled_x * cos_r - scaled_z * sin_r
                rot_z = scaled_x * sin_r + scaled_z * cos_r
                
                # 4. Trasladar a posición del mundo
                world_x = rot_x + entity_pos.x
                world_z = rot_z + entity_pos.z
                world_y = entity_pos.y  # Altura de dibujo = posición Y del blueprint
                
                self.cnc_trajectory.append({
                    'pos': (world_x, world_y, world_z),
                    'pen': wp['pen']
                })
        
        if not self.cnc_trajectory:
            print("[CNC] Error: Trayectoria vacía.")
            self._send_cnc_status("error", "Trayectoria vacía")
            return
        
        # Log primeros waypoints para verificación
        for i, wp in enumerate(self.cnc_trajectory[:3]):
            print(f"  WP[{i}]: pos={wp['pos']}, pen={'DOWN' if wp['pen'] else 'UP'}")
        
        self.cnc_index = 0
        self.cnc_active = True
        
        # Inicializar posición lógica del interpolador
        first_wp = self.cnc_trajectory[0]
        start_pos = Vec3(first_wp['pos'])
        if not first_wp['pen']:
            start_pos.y += self.cnc_safety_height
        self.cnc_logical_pos = start_pos
        
        self._send_cnc_status("running")
        print(f"[CNC] Iniciando trayectoria con {len(self.cnc_trajectory)} puntos.")


    def _update_cnc_execution(self):
        """Mueve el brazo suavemente hacia el waypoint actual usando interpolación por tiempo."""
        if self.cnc_index >= len(self.cnc_trajectory):
            self.cnc_active = False
            self._send_cnc_status("completed")
            print("[CNC] Trayectoria completada.")
            if hasattr(self, 'cnc_logical_pos'): del self.cnc_logical_pos
            return
            
        target = self.cnc_trajectory[self.cnc_index]
        target_pos = Vec3(target['pos'])
        pen_down = target['pen']
        
        if not pen_down:
            target_pos.y += self.cnc_safety_height

        # ── Interpolación de posición (Feedrate constante) ──
        if not hasattr(self, 'cnc_logical_pos'):
            self.cnc_logical_pos = Vec3(target_pos)

        direction = target_pos - self.cnc_logical_pos
        distance_to_wp = direction.length()
        
        # Velocidad de movimiento (más rápida si el pen está arriba)
        current_speed = self.cnc_feedrate * (3.0 if not pen_down else 1.0)
        move_step = current_speed * time.dt
        
        if move_step >= distance_to_wp or distance_to_wp < 0.001:
            # Hemos llegado al waypoint
            self.cnc_logical_pos = Vec3(target_pos)
            self.cnc_index += 1
        else:
            # Avanzar proporcionalmente
            self.cnc_logical_pos += direction.normalized() * move_step
        
        # ── Resolver IK y aplicar ──
        angles = self.ik_solver.solve(self.cnc_logical_pos)
        
        if angles:
            self._apply_angles_batched(angles)
            
            # ── Actualizar rastro visual (solo si el pen está abajo) ──
            if pen_down:
                if not hasattr(self, '_last_trace_pos') or (self.cnc_logical_pos - self._last_trace_pos).length() > 0.02:
                    # Usar pares de vértices para modo 'line': cada segmento es (v_prev, v_curr)
                    if hasattr(self, '_last_trace_pos') and getattr(self, '_pen_was_down', False):
                        # Continuación de trazo: añadir segmento desde el último punto
                        self.drawing_trace.model.vertices.append(Vec3(self._last_trace_pos))
                        self.drawing_trace.model.vertices.append(Vec3(self.cnc_logical_pos))
                    # Si es el inicio de un nuevo trazo, solo guardamos la posición
                    
                    self.drawing_trace.model.generate()
                    self._last_trace_pos = Vec3(self.cnc_logical_pos)
            
            self._pen_was_down = pen_down
            self.sync_to_gui()
        else:
            # Punto inalcanzable: avanzar al siguiente y actualizar posición lógica
            print(f"[CNC] Punto inalcanzable en index {self.cnc_index}, saltando...")
            self.cnc_index += 1
            if self.cnc_index < len(self.cnc_trajectory):
                next_wp = self.cnc_trajectory[self.cnc_index]
                self.cnc_logical_pos = Vec3(next_wp['pos'])
                if not next_wp['pen']:
                    self.cnc_logical_pos.y += self.cnc_safety_height
            # Marcar pen como up para no arrastrar líneas al punto siguiente
            self._pen_was_down = False
            if hasattr(self, '_last_trace_pos'): del self._last_trace_pos

        # Enviar progreso periódicamente (~5Hz)
        if self.cnc_index % max(1, len(self.cnc_trajectory) // 50) == 0:
            progress = int((self.cnc_index / len(self.cnc_trajectory)) * 100)
            self._send_cnc_status("running", progress=progress)
        
        # ── Actualizar colores de los trazos del blueprint (progreso visual) ──
        bp = self.svg_blueprint
        if bp and bp.model and hasattr(bp, 'seg_wp_end'):
            seg_map = bp.seg_wp_end
            num_segs = len(seg_map)
            # Solo actualizar cada ~30 pasos para rendimiento
            if num_segs > 0 and self.cnc_index % max(1, num_segs // 30) == 0:
                col_done = color.rgba(50, 255, 50, 255)      # Verde brillante - completado
                col_curr = color.rgba(255, 255, 0, 255)      # Amarillo - segmento actual
                col_pending = color.rgba(0, 200, 255, 100)   # Cyan tenue - pendiente
                
                new_colors = []
                for s in range(num_segs):
                    end_idx = seg_map[s]
                    if self.cnc_index > end_idx:
                        c = col_done
                    elif self.cnc_index >= end_idx - 1:
                        c = col_curr
                    else:
                        c = col_pending
                    new_colors.append(c)  # Vértice inicio del segmento
                    new_colors.append(c)  # Vértice fin del segmento
                
                bp.model.colors = new_colors
                bp.model.generate()

    def _reset_cnc_trace(self):
        """Limpia el rastro visual y reinicia el índice si no está en marcha."""
        if self.drawing_trace:
            self.drawing_trace.model.vertices = []
            self.drawing_trace.model.generate()
        self._trace_segments = []
        
        # Resetear colores de los trazos del blueprint a cyan por defecto
        if self.svg_blueprint and self.svg_blueprint.model:
            vert_count = getattr(self.svg_blueprint, 'vert_count', 0)
            if vert_count > 0:
                self.svg_blueprint.model.colors = [color.rgba(0, 200, 255, 180)] * vert_count
                self.svg_blueprint.model.generate()
        
        if not self.cnc_active:
            self.cnc_index = 0
            self._send_cnc_status("loaded", progress=0)
        
        if hasattr(self, '_last_trace_pos'): del self._last_trace_pos
        if hasattr(self, '_pen_was_down'): del self._pen_was_down
        print("[CNC] Rastro visual reiniciado.")

    def _update_blueprint_reachability(self):
        """Colorea cada segmento de línea del SVG según alcanzabilidad del IK.
        Verde = alcanzable, Rojo = fuera de rango."""
        bp = self.svg_blueprint
        if not bp or not bp.model or not bp.model.vertices:
            return
        
        entity_pos = bp.world_position
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        verts = bp.model.vertices
        new_colors = []
        
        col_ok = color.rgba(0, 255, 100, 220)    # Verde brillante
        col_bad = color.rgba(255, 40, 40, 240)    # Rojo brillante
        
        for v in verts:
            # v es (local_x, 0, local_z) en espacio local del mesh
            scaled_x = v[0] * entity_scale.x
            scaled_z = v[2] * entity_scale.z
            
            rot_x = scaled_x * cos_r - scaled_z * sin_r
            rot_z = scaled_x * sin_r + scaled_z * cos_r
            
            world_x = rot_x + entity_pos.x
            world_z = rot_z + entity_pos.z
            world_y = entity_pos.y
            
            result = self.ik_solver.solve((world_x, world_y, world_z))
            new_colors.append(col_ok if result else col_bad)
        
        bp.model.colors = new_colors
        bp.model.generate()

    def _send_cnc_status(self, status, error_msg=None, progress=0):
        """Envía el estado actual del CNC a la GUI del Lab."""
        msg = json.dumps({
            "type": "cnc_status",
            "status": status,  # loaded, running, completed, stopped, error
            "progress": progress,
            "error": error_msg
        })
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except Exception:
            pass


    def _send_collision_status(self):
        """Send current collision state to the GUI."""
        colliding = self.collision_mgr.is_colliding()
        probes = self.collision_mgr.get_colliding_probes() if colliding else []
        msg = json.dumps({
            "type": "collision_status",
            "colliding": colliding,
            "joints": probes
        })
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except Exception:
            pass

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
