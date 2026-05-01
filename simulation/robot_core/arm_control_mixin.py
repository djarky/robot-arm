from ursina.physics import physics_handler
from panda3d.bullet import BulletTriangleMesh, BulletTriangleMeshShape, BulletRigidBodyNode
from direct.actor.Actor import Actor
import os

class ArmControlMixin:
    """Mixin for arm angles and colliders."""
    
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
        """Configura el acceso a las animaciones de la garra integrada en el Actor."""
        # En el nuevo sistema unificado, self.actor ya contiene las partes 'claw1' y 'claw2'
        # No necesitamos crear actores separados, solo validar que las partes existen.
        print(f"[Gripper] Sistema de animación unificado listo para claw1 y claw2")

    def set_gripper_state(self, ratio):
        """Controla la apertura de la garra (0.0 cerrado, 1.0 abierto)."""
        # Partes definidas en el constructor de Actor en RobotArmSim
        parts = ["claw1", "claw2"]
        
        for p in parts:
            try:
                num_frames = self.actor.getNumFrames("open", partName=p)
                if num_frames > 0:
                    frame = int(ratio * (num_frames - 1))
                    self.actor.pose("open", frame, partName=p)
            except Exception as e:
                # Silencioso si la parte no tiene la animación cargada
                pass
