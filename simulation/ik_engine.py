import math
import numpy as np

class IK_Solver:
    """
    Inverse Kinematics solver for a 6-DOF Anthropomorphic robot arm.
    
    Coordinate System (Ursina/Panda3D mapping):
    - Y: Vertical Height (Up)
    - X, Z: Horizontal Plane
    """
    
    def __init__(self, l1=1.089, l2=1.101, d1=0.557, tool_offset=(0, 1.116, 0)):
        # Default lengths based on model analysis (scaled units)
        self.L1 = l1  # Shoulder to Elbow
        self.L2 = l2  # Elbow to Wrist
        self.D1 = d1  # Base to Shoulder height
        self.TOOL_OFFSET = np.array(tool_offset) # Wrist center to tip (vector)
        self.L_TOOL = np.linalg.norm(self.TOOL_OFFSET)
        
        # Joint limits (degrees)
        self.limits = [(-90, 90)] * 5

    def solve(self, target_pos, target_up=None):
        """
        Calculates joint angles for a target position (x, y, z).
        target_pos: (x, y, z) in world coordinates.
        target_up: (ux, uy, uz) direction for the gripper (default: pointing down).
        
        Returns: List of 5 angles [j0...j4] in degrees, or None if unreachable.
        """
        tx, ty, tz = target_pos
        
        # 1. Base Angle (J0)
        # Using atan2(z, x) because in this sim X/Z is the floor.
        theta0 = math.degrees(math.atan2(tz, tx))
        
        # 2. Wrist Center Calculation (Decoupling)
        # We calculate the wrist position such that the TOOL_OFFSET (when rotated)
        # ends up at the target_pos.
        
        # For CNC/Drawing, we assume the tool is pointing DOWN (-Y in IK space).
        # This means J4 (pitch) compensates for J1 and J2.
        # Simple Case: The tool is pointing straight down.
        # If the tool has a lateral offset, it must be accounted for.
        
        if target_up is None:
            # Assume tool points DOWN (-Y). 
            # If TOOL_OFFSET is (0, L, 0) in rest pose, and we point down,
            # wrist is at target_pos + (0, L, 0).
            # If TOOL_OFFSET has X/Z, we need to rotate it with J0.
            
            # Rotate TOOL_OFFSET by J0 (theta0)
            rad0 = math.atan2(tz, tx)
            c0, s0 = math.cos(rad0), math.sin(rad0)
            
            # Local offset rotated to match J0 orientation
            # Assuming TOOL_OFFSET is in a local frame where Y is "along the arm" 
            # and X/Z are lateral.
            # Local offset rotated to match J0 orientation
            # Standardize sign: we use the absolute L_TOOL magnitude for the vertical component 
            # to ensure the wrist is ALWAYS above the drawing tip, immune to calibration sign errors.
            off_x, _, off_z = self.TOOL_OFFSET
            v_off_y = self.L_TOOL 
            
            wrist_center = (
                tx - (off_x * c0 - off_z * s0),
                ty + v_off_y, 
                tz - (off_x * s0 + off_z * c0)
            )
            
        # 3. 2D Plane Geometry (J1, J2)
        # Project wrist center to 2D plane (r, y_rel)
        r = math.sqrt(wrist_center[0]**2 + wrist_center[2]**2)
        y_rel = wrist_center[1] - self.D1
        
        # Distance from Shoulder to Wrist Center
        D = math.sqrt(r**2 + y_rel**2)
        
        # Margen de tolerancia para evitar errores de precisión (2cm)
        epsilon = 0.02
        max_reach = self.L1 + self.L2
        
        if D > (max_reach + epsilon):
            # PROYECCIÓN: El punto está fuera de alcance. 
            # Re-escalamos el objetivo para que esté justo en el borde del alcance máximo.
            scale = max_reach / D
            r *= scale
            y_rel *= scale
            # Recalcular D para que sea exacto
            D = math.sqrt(r**2 + y_rel**2)
            # No retornamos None aquí, permitimos que el brazo se estire al máximo
        elif D < (abs(self.L1 - self.L2) - epsilon):
            # Demasiado cerca del hombro
            return None # Unreachable
            
        # Law of Cosines for J2 (Elbow)
        # cos_beta = (L1^2 + L2^2 - D^2) / (2 * L1 * L2)
        cos_beta = (self.L1**2 + self.L2**2 - D**2) / (2 * self.L1 * self.L2)
        beta = math.acos(np.clip(cos_beta, -1, 1))
        theta2 = math.degrees(beta) - 180 # Adjust for joint zero orientation
        
        # Angle of the vector D
        phi1 = math.atan2(y_rel, r)
        # Internal angle alpha
        cos_alpha = (self.L1**2 + D**2 - self.L2**2) / (2 * self.L1 * D)
        alpha = math.acos(np.clip(cos_alpha, -1, 1))
        
        theta1 = math.degrees(phi1 + alpha) - 90 # Adjust for J1 being vertical at 0
        
        # 4. Orientation (J3, J4, J5)
        # Simplified for "pointing down" trayectories:
        # If we want to stay pointing down while J1, J2 move:
        # J4 (Wrist Pitch) compensates J1 and J2
        theta4 = -(theta1 + theta2)
        
        # J3 and J5 can remain at 0 for planar 2D drawing unless rotation is needed
        theta3 = 0
        theta5 = 0
        
        angles = [theta0, theta1, theta2, theta3, theta4]
        
        # Apply limits strictly
        rounded_angles = []
        for i, a in enumerate(angles):
            low, high = self.limits[i]
            val = round(a, 2)
            if val < low or val > high:
                print(f"  [IK DEBUG] Joint {i} out of range: {val} (Limits: {low} to {high})")
                return None
            rounded_angles.append(val)
            
        return rounded_angles

# Test if executed directly
if __name__ == "__main__":
    solver = IK_Solver()
    res = solver.solve((2, 0.5, 0)) # Point in front of robot
    print(f"Test Solution: {res}")
