"""
simulation/collision_aware_interpolator.py — Safe path planning for animations.

When a direct interpolation between two poses would cause the arm to pass
through the floor, this module generates intermediate waypoints that lift
the arm, transition horizontally, and then lower to the target.

Classes:
    CollisionAwareInterpolator — Plans evasion manoeuvres in 3 phases.
"""
import math


class CollisionAwareInterpolator:
    """Plans collision-free paths between two joint configurations.

    The strategy is:
        1.  Sample the direct interpolation at N points.
        2.  If any sample collides with the floor, generate a 3-phase
            detour:
              A. LIFT   — raise J1/J2 until the arm clears the floor.
              B. TRANSIT — with the arm raised, rotate J0/J3 to the
                           target values (horizontal moves, safe).
              C. LOWER  — descend J1/J2/J4/J5 to the final target,
                           checking collision at each micro-step.

    Parameters
    ----------
    sim : RobotArmSim
        Reference to the simulation for collision checks.
    """

    # How many sample points along the direct path to test
    SAMPLE_STEPS = 20

    # How many degrees to increment J1/J2 when searching for a safe lift
    LIFT_INCREMENT = 5

    def __init__(self, sim):
        self.sim = sim

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_safe_path(self, start_angles, end_angles):
        """Return a list of waypoint angle-lists from start to end.

        If the direct path is collision-free, returns ``[end_angles]``.
        Otherwise returns ``[lift_angles, transit_angles, end_angles]``.

        Parameters
        ----------
        start_angles : list[float]
            Current joint angles (6 values).
        end_angles : list[float]
            Target joint angles (6 values).

        Returns
        -------
        list[list[float]]
            Ordered waypoints including the final target.  The caller
            should interpolate between consecutive waypoints.
        bool
            ``True`` if evasion was needed.
        """
        # Pad to 6 if needed
        start = self._pad(start_angles)
        end = self._pad(end_angles)

        # 1. Check direct path for collisions
        if not self._direct_path_collides(start, end):
            return [end], False

        print("[Interpolator] Direct path collides — planning evasion")

        # 2. Phase A: find safe lift from START configuration
        lift_angles = self._find_safe_lift(start)
        if lift_angles is None:
            # Could not find a safe lift — fall back to direct (best effort)
            print("[Interpolator] WARNING: could not find safe lift, using direct path")
            return [end], False

        # 3. Phase B: transit — keep J1/J2 from lift, set J0/J3 to target
        transit_angles = list(lift_angles)
        transit_angles[0] = end[0]  # J0 (YAW base) → target
        transit_angles[3] = end[3]  # J3 (YAW wrist) → target

        # Verify the transit position is also safe
        if self.sim.collision_mgr.test_angles(transit_angles):
            # Even the transit collides — try lifting more
            transit_angles = self._find_safe_lift(transit_angles)
            if transit_angles is None:
                print("[Interpolator] WARNING: transit lift failed, using direct path")
                return [end], False

        # 4. Phase C: lower from transit to end
        #    The end itself might collide.  If so, we let _apply_angle's
        #    per-step blocking handle it.  We just provide the waypoints.

        return [lift_angles, transit_angles, end], True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pad(self, angles):
        """Ensure angles list has exactly 6 elements."""
        a = list(angles)
        while len(a) < 6:
            a.append(0)
        return a[:6]

    def _lerp_angles(self, a, b, t):
        """Linearly interpolate between two angle lists."""
        return [a[i] + (b[i] - a[i]) * t for i in range(len(a))]

    def _direct_path_collides(self, start, end):
        """Sample SAMPLE_STEPS points along the direct interpolation and
        return True if any of them collides."""
        for step in range(1, self.SAMPLE_STEPS + 1):
            t = step / self.SAMPLE_STEPS
            test = self._lerp_angles(start, end, t)
            if self.sim.collision_mgr.test_angles(test):
                return True
        return False

    def _find_safe_lift(self, base_angles):
        """Starting from base_angles, incrementally raise J1 (and J2)
        until no probe collides.

        Returns the safe configuration, or None if 90° of lift was not
        enough (unlikely for a floor-only scenario).
        """
        test = list(base_angles)
        for lift_deg in range(0, 91, self.LIFT_INCREMENT):
            # J1 is ROLL — negative rotation lifts the arm upward
            test[1] = max(-90, min(90, base_angles[1] - lift_deg))
            # J2 assists with half the lift
            test[2] = max(-90, min(90, base_angles[2] - lift_deg // 2))
            if not self.sim.collision_mgr.test_angles(test):
                return list(test)
        return None
