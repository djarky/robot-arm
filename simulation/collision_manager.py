"""
simulation/collision_manager.py — Collision detection for the robot arm.

Uses "probes" (exposed joint nodes) to detect when parts of the arm
are at or below the floor level.  Much lighter than mesh colliders.

Classes:
    CollisionManager — Manages probe points on the skeleton, checks floor
                       penetration, provides debug visualisation (F3).
"""
import math
from ursina import *


# Each probe: (name, joint_name, local_offset)
# The offset is in the joint's LOCAL space.
# Diagnostics show joint world Y ranges from ~17 (J0) to ~92 (J5) at rest.
PROBE_CONFIG = [
    ("J0_base",   "J0", Vec3(0, 0, 0)),
    ("J1_elbow",  "J1", Vec3(0, 0, 0)),
    ("J2_mid",    "J2", Vec3(0, 0, 0)),
    ("J2_tip",    "J2", Vec3(0, 0, 0.5)),
    ("J3_wrist",  "J3", Vec3(0, 0, 0)),
    ("J4_hand",   "J4", Vec3(0, 0, 0)),
    ("J5_grip",   "J5", Vec3(0, 0, 0)),
    ("J5_tip",    "J5", Vec3(0, 0, 0.3)),
]


class CollisionManager:
    """Lightweight collision system based on skeleton probes.

    Instead of attaching heavy mesh colliders to every GeomNode of the
    robot model, we place invisible "probe" points at key locations on
    the skeleton (joint pivots and link tips).  Each frame we read their
    world-space Y coordinate and compare it against the floor level plus
    a safety margin.

    Parameters
    ----------
    sim : RobotArmSim
        Reference to the simulation so we can access the Actor, floor, etc.
    safety_margin : float
        Minimum allowed distance (Ursina world units) between any probe
        and the floor surface.  The model's coordinates are large (~17-92
        at rest), so this margin should be generous.  Default 5.0.
    """

    def __init__(self, sim, safety_margin=5.0):
        self.sim = sim
        self.safety_margin = safety_margin

        # The Ursina floor entity sits at y=0 and has no thickness.
        self.floor_y = 0.0  # top surface of the plane

        # Exposed joint NodePaths (Panda3D) — follow the skeleton in
        # real time even after controlJoint moves bones.
        self.probe_exposed = {}   # name → NodePath
        self.probe_configs = {}   # name → (joint_name, local_offset)

        # Collision state per probe
        self.collision_state = {}  # name → bool

        # Debug visualisation entities (created lazily)
        self._debug_enabled = False
        self._debug_spheres = {}   # name → Entity

        self._setup_probes()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_probes(self):
        """Create exposed joints for each probe point."""
        for probe_name, joint_name, offset in PROBE_CONFIG:
            try:
                exposed = self.sim.actor.exposeJoint(None, "modelRoot", joint_name)
                self.probe_exposed[probe_name] = exposed
                self.probe_configs[probe_name] = (joint_name, offset)
                self.collision_state[probe_name] = False
            except Exception as e:
                print(f"  [CollisionManager] Could not expose '{joint_name}' "
                      f"for probe '{probe_name}': {e}")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_probe_world_positions(self):
        """Return {probe_name: Vec3} with world-space positions.

        For probes with a non-zero local offset, we transform the offset
        through the joint's world matrix so it follows the bone correctly.
        """
        # CRITICAL: Force Panda3D to calculate the new skeleton pose before reading
        if self.sim and hasattr(self.sim, 'actor'):
            try:
                self.sim.actor.getPartBundle('modelRoot').forceUpdate()
            except Exception:
                pass

        positions = {}
        for name, exposed in self.probe_exposed.items():
            _, offset = self.probe_configs[name]
            if offset.length() < 0.001:
                wp = exposed.getPos(render)
                positions[name] = Vec3(wp.x, wp.y, wp.z)
            else:
                world_mat = exposed.getMat(render)
                world_pt = world_mat.xformPoint(offset)
                positions[name] = Vec3(world_pt.x, world_pt.y, world_pt.z)
        return positions

    def get_min_probe_y(self):
        """Return the lowest Y coordinate across all probes.

        This is the primary metric for collision — it tells us how
        close the nearest point of the arm is to the floor.
        """
        positions = self.get_probe_world_positions()
        if not positions:
            return 999.0
        return min(pos.y for pos in positions.values())

    def check_floor_collision(self):
        """Update and return {probe_name: bool} — True if probe is at or
        below the floor + safety_margin."""
        positions = self.get_probe_world_positions()
        threshold = self.floor_y + self.safety_margin
        for name, pos in positions.items():
            self.collision_state[name] = pos.y <= threshold
        return dict(self.collision_state)

    def is_colliding(self):
        """Return True if ANY probe is colliding with the floor."""
        self.check_floor_collision()
        return any(self.collision_state.values())

    def get_colliding_probes(self):
        """Return list of probe names currently in collision."""
        self.check_floor_collision()
        return [name for name, hit in self.collision_state.items() if hit]

    # ------------------------------------------------------------------
    # Smart collision check (for _apply_angle)
    # ------------------------------------------------------------------

    def would_worsen(self, old_min_y):
        """Check if the current configuration is WORSE than before.

        This is the key to avoiding the "stuck" problem: if the arm is
        already near/in collision, we should still allow movements that
        RAISE the lowest probe (improve the situation).

        Parameters
        ----------
        old_min_y : float
            The minimum probe Y before the angle change.

        Returns
        -------
        bool
            True if the change should be BLOCKED (arm went lower or
            into collision territory from a safe position).
        """
        new_min_y = self.get_min_probe_y()
        threshold = self.floor_y + self.safety_margin

        # Case 1: Was safe, now in collision → BLOCK
        if old_min_y > threshold and new_min_y <= threshold:
            return True

        # Case 2: Was already in collision, got WORSE → BLOCK
        if old_min_y <= threshold and new_min_y < old_min_y:
            return True

        # Case 3: Was in collision but improved (or stayed same) → ALLOW
        # Case 4: Was safe, still safe → ALLOW
        return False

    # ------------------------------------------------------------------
    # Tentative testing  (used by interpolator)
    # ------------------------------------------------------------------

    def test_angles(self, angles):
        """Temporarily apply a set of angles, check collision, then revert.

        Parameters
        ----------
        angles : list[float]
            Full list of joint angles (len == NUM_JOINTS).

        Returns
        -------
        bool
            True if the configuration causes collision.
        """
        saved = list(self.sim.angles)
        for i, a in enumerate(angles):
            self.sim._apply_angle_raw(i, a)
        colliding = self.is_colliding()
        for i, a in enumerate(saved):
            self.sim._apply_angle_raw(i, a)
        return colliding

    # ------------------------------------------------------------------
    # Debug visualisation
    # ------------------------------------------------------------------

    def toggle_debug(self):
        """Toggle the debug sphere overlay on/off."""
        self._debug_enabled = not self._debug_enabled
        if self._debug_enabled:
            self._create_debug_spheres()
            print("[Collision] Debug probes ON")
        else:
            self._destroy_debug_spheres()
            print("[Collision] Debug probes OFF")

    def _create_debug_spheres(self):
        """Create small semi-transparent spheres at each probe location."""
        for name in self.probe_exposed:
            if name not in self._debug_spheres:
                sphere = Entity(
                    model='sphere',
                    scale=1.5,  # Bigger for visibility at model scale
                    color=color.rgba(0, 1, 0, 0.5),
                    unlit=True,
                    always_on_top=True,
                )
                self._debug_spheres[name] = sphere

    def _destroy_debug_spheres(self):
        """Remove all debug spheres."""
        for s in self._debug_spheres.values():
            destroy(s)
        self._debug_spheres.clear()

    def update_debug_visuals(self):
        """Move debug spheres to current probe positions and colour them."""
        if not self._debug_enabled:
            return
        positions = self.get_probe_world_positions()
        self.check_floor_collision()
        threshold = self.floor_y + self.safety_margin
        for name, sphere in self._debug_spheres.items():
            if name in positions:
                sphere.position = positions[name]
                probe_y = positions[name].y
                if self.collision_state.get(name, False):
                    sphere.color = color.rgba(1, 0, 0, 0.7)  # Red = colliding
                elif probe_y < threshold + 5:
                    sphere.color = color.rgba(1, 1, 0, 0.6)  # Yellow = close
                else:
                    sphere.color = color.rgba(0, 1, 0, 0.5)  # Green = free
