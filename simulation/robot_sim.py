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
        
        # Instanciar el Gizmo Universal
        self.gizmo = TransformationGizmo()
        
        # ── Gestión de Spawn Relativo ──
        self.pending_spawn_data = None
        # Cursor visual para el spawn (un icono/esfera semitransparente)
        self.spawn_preview = Entity(
            model='sphere', 
            scale=0.3, 
            color=color.rgba(1, 1, 0, 0.6), 
            enabled=False,
            always_on_top=True
        )
        
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

    def spawn_object(self, shape, size, mass, position=None):
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
                    # Aplicar ángulos recibidos a las rotaciones (sobrescribe la entrada del ratón)
                    for i in range(min(len(incoming), self.NUM_JOINTS)):
                        self._apply_angle(i, incoming[i])
                    
                    # Forzar sincronización de vuelta con la GUI. 
                    # Si la colisión bloqueó y revirtió algún ángulo, esto hará que
                    # el slider de Qt regrese instantáneamente a la posición permitida.
                    self.sync_to_gui()
                    
                    # Send collision status back to GUI
                    self._send_collision_status()
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
                        "mass": msg["mass"]
                    }
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
            except Exception as e:
                print("Error decodificando UDP:", e)

        # ── Lógica de Spawn Relativo (Preview y Click) ──
        if self.pending_spawn_data:
            # Mostrar preview solo si el ratón toca una superficie (suelo u objeto)
            if mouse.world_point:
                self.spawn_preview.enabled = True
                # Ajustar la altura según el tamaño del objeto para que no se entierre
                h = self.pending_spawn_data["size"] / 2
                self.spawn_preview.position = mouse.world_point + Vec3(0, h, 0)
                
                # Click izquierdo para confirmar spawn
                if mouse.left:
                    self.spawn_object(
                        self.pending_spawn_data["shape"],
                        self.pending_spawn_data["size"],
                        self.pending_spawn_data["mass"],
                        position=self.spawn_preview.position
                    )
                    self.pending_spawn_data = None
                    self.spawn_preview.enabled = False
                    print(f"Objeto spawneado en {self.spawn_preview.position}")
            else:
                self.spawn_preview.enabled = False
            
            # Click derecho o Escape para cancelar siempre (esté o no sobre superficie)
            if mouse.right or held_keys['escape']:
                self.pending_spawn_data = None
                self.spawn_preview.enabled = False
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
                else:
                    # Deseleccionar al hacer clic en el vacío
                    self.gizmo.detach()
