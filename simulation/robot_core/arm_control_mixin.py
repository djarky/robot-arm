from ursina.physics import physics_handler
from panda3d.bullet import BulletTriangleMesh, BulletTriangleMeshShape, BulletRigidBodyNode
from direct.actor.Actor import Actor
from panda3d.core import Vec3
import os

class ArmControlMixin:
    """Mixin for arm angles and colliders."""
    
    # Per-joint angle limits: J4 (wrist pitch) needs wider range
    # because it compensates J1+J2 to keep the tool pointing down.
    JOINT_LIMITS = [(-90, 90), (-90, 90), (-90, 90), (-90, 90), (-180, 180)]

    def _apply_angle_raw(self, joint_index, angle_deg):
        """Apply angle WITHOUT collision check.  Used internally by
        the collision system for tentative testing."""
        lo, hi = self.JOINT_LIMITS[joint_index] if joint_index < len(self.JOINT_LIMITS) else (-90, 90)
        clamped = max(lo, min(hi, angle_deg))
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

    def _setup_gripper_actors(self, model_path):
        """Configura sub-actores para las pinzas de la garra.
        Esto permite usar el sistema de animaciones de Panda3D de forma limpia."""
        self.gripper_actors = {}
        
        # Mapeo de personajes a sus animaciones correspondientes según la inspección del GLB
        mapping = {
            "1arm": "1armAction",
            "2arm": "2armAction"
        }
        
        for char_name, anim_name in mapping.items():
            char_node = self.actor.find(f"**/{char_name}")
            if not char_node.isEmpty():
                try:
                    # Guardamos el padre original antes de crear el Actor
                    # (El constructor de Actor reparenta el nodo a su propia raíz)
                    original_parent = char_node.getParent()
                    
                    # Creamos un Actor independiente usando el nodo original (copy=False)
                    act = Actor(char_node, {anim_name: char_node}, copy=False)
                    
                    # Re-vinculamos el Actor a la jerarquía original
                    if original_parent:
                        act.reparentTo(original_parent)
                    
                    # Resetear transformaciones locales (limpieza estándar)
                    act.clearTransform()
                    char_node.clearTransform()
                    
                    # AUTO-ALINEACIÓN Y ESCALA: 
                    # 1. Resetear posición de los huesos para pegar las piezas a la tapa.
                    # 2. Sincronizar escala mundial con la base de la garra.
                    act.update()
                    
                    # Buscamos la referencia de posición (tapa) y escala (base)
                    tapa_ref = self.actor.find("**/tapa-garra")
                    base_ref = self.actor.find("**/base-de-la-garra")
                    ref_scale = base_ref.getScale(self.actor.getParent()) if not base_ref.isEmpty() else 1.0
                    
                    # Ajuste fino de posición (en unidades del mundo)
                    # Queremos bajar las pinzas 0.5 unidades hacia abajo en el mundo.
                    # Usamos getRelativeVector para que el offset siempre sea hacia el suelo.
                    world_offset = Vec3(0, -0.5, 0)
                    local_offset = act.getRelativeVector(self.actor.getParent(), world_offset)
                    
                    # Calcular posición de la tapa relativa al Actor de la pinza
                    if not tapa_ref.isEmpty():
                        target_pos = tapa_ref.getPos(act) + local_offset
                    else:
                        target_pos = (0, 0, 0)
                    
                    for bone_name in ['gear', 'J-dump-c']:
                        try:
                            ctrl = act.controlJoint(None, 'modelRoot', bone_name)
                            if ctrl and not ctrl.isEmpty():
                                ctrl.setPos(target_pos)
                        except Exception:
                            pass
                    
                    # CORRECCIÓN DE POSICIÓN Y TAMAÑO: 
                    # Sincronizar escala mundial con la base y resetear offsets locales
                    # para que la malla se pegue exactamente al hueso alineado.
                    for mesh in act.findAllMatches("**/+GeomNode"):
                        mesh.setPos(0, 0, 0)
                        mesh.setHpr(0, 0, 0)
                        mesh.setScale(self.actor.getParent(), ref_scale)
                    
                    self.gripper_actors[char_name] = (act, anim_name)
                    print(f"[Gripper] Actor vinculado, alineado y escalado para '{char_name}'")
                except Exception as e:
                    print(f"[Gripper] Error al crear actor para '{char_name}': {e}")
        
        if not self.gripper_actors:
            print("[Gripper] Advertencia: No se pudieron crear los sub-actores de la garra.")

    def set_gripper_state(self, ratio):
        """Controla la apertura de la garra (0.0 cerrado, 1.0 abierto).
        Usa el sistema de poses del Actor para mayor precisión."""
        if not hasattr(self, 'gripper_actors') or not self.gripper_actors:
            return
            
        ratio = max(0.0, min(1.0, ratio))
        for act, anim_name in self.gripper_actors.values():
            try:
                num_frames = act.getNumFrames(anim_name)
                frame = int(ratio * (num_frames - 1))
                act.pose(anim_name, frame)
            except Exception as e:
                pass
