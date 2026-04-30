import math
import numpy as np

class IK_Solver:
    """
    Inverse Kinematics solver for a 6-DOF Anthropomorphic robot arm.
    
    Coordinate System (Ursina/Panda3D mapping):
    - Y: Vertical Height (Up)
    - X, Z: Horizontal Plane
    """
    
    def __init__(self, l1=1.09, l2=1.10, d1=0.65, tool_length=0.45):
        # Default lengths based on model analysis (scaled units)
        self.L1 = l1  # Shoulder to Elbow
        self.L2 = l2  # Elbow to Wrist
        self.D1 = d1  # Base to Shoulder height
        self.L_TOOL = tool_length # Wrist center to tip
        
        # Joint limits (degrees)
        self.limits = [(-90, 90)] * 6

    def solve(self, target_pos, target_up=None):
        """
        Calculates joint angles for a target position (x, y, z).
        target_pos: (x, y, z) in world coordinates.
        target_up: (ux, uy, uz) direction for the gripper (default: pointing down).
        
        Returns: List of 6 angles [j0...j5] in degrees, or None if unreachable.
        """
        tx, ty, tz = target_pos
        
        # 1. Base Angle (J0)
        # Using atan2(z, x) because in this sim X/Z is the floor.
        theta0 = math.degrees(math.atan2(tz, tx))
        
        # 2. Wrist Center Calculation (Decoupling)
        # For drawing, we usually want the gripper pointing straight down (-Y).
        if target_up is None:
            # Default: Pointing down (Y negative)
            wrist_center = (tx, ty + self.L_TOOL, tz)
        else:
            ux, uy, uz = target_up
            wrist_center = (
                tx - ux * self.L_TOOL,
                ty - uy * self.L_TOOL,
                tz - uz * self.L_TOOL
            )
            
        # 3. 2D Plane Geometry (J1, J2)
        # Project wrist center to 2D plane (r, y_rel)
        r = math.sqrt(wrist_center[0]**2 + wrist_center[2]**2)
        y_rel = wrist_center[1] - self.D1
        
        # Distance from Shoulder to Wrist Center
        D = math.sqrt(r**2 + y_rel**2)
        
        if D > (self.L1 + self.L2) or D < abs(self.L1 - self.L2):
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
        
        angles = [theta0, theta1, theta2, theta3, theta4, theta5]
        
        # Apply limits strictly
        rounded_angles = []
        for i, a in enumerate(angles):
            low, high = self.limits[i]
            val = round(a, 2)
            if val < low or val > high:
                return None  # Unreachable due to physical joint limits
            rounded_angles.append(val)
            
        return rounded_angles

# Test if executed directly
if __name__ == "__main__":
    solver = IK_Solver()
    res = solver.solve((2, 0.5, 0)) # Point in front of robot
    print(f"Test Solution: {res}")
