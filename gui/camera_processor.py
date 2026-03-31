import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

class CameraProcessorMixin:
    """Mixin that handles pose estimation logic, smoothing, and status for the camera tracking."""

    def process_pose_data(self, frame, pose_landmarks_list, hand_landmarks_list, is_playing, is_left_handed=False):
        """
        Extracts joint angles from pose and hand landmarks, applies smoothing (EMA),
        and draws the skeletons on the frame.
        
        Returns: (processed_frame, angles, arm_visible, low_confidence)
        """
        h_f, w_f, _ = frame.shape
        
        # Default angles (persistence) - now 6 axes
        current_angles = list(self.smooth_camera_angles)
        
        arm_visible = False
        low_confidence = False
        
        # 1. Pose Logic Layer: Extract Base, Shoulder, Elbow (J0, J1, J2)
        if not is_playing and pose_landmarks_list:
            for pose_lms in pose_landmarks_list:
                try:
                    # Due to horizontal mirroring (cv2.flip), the user's Right arm 
                    # appears as "Left" (indices 11, 13, 15) to MediaPipe, and vice versa.
                    if is_left_handed:
                        j_shoulder = pose_lms[12]
                        j_elbow = pose_lms[14]
                        j_wrist = pose_lms[16]
                    else:
                        j_shoulder = pose_lms[11]
                        j_elbow = pose_lms[13]
                        j_wrist = pose_lms[15]
                    
                    # Validation
                    threshold = 0.5
                    if (j_shoulder.visibility < threshold or 
                        j_elbow.visibility < threshold or 
                        j_wrist.visibility < threshold):
                        low_confidence = True
                        continue
                    
                    arm_visible = True

                    # Calculate target angles for Arm
                    v1 = np.array([j_elbow.x - j_shoulder.x, j_elbow.y - j_shoulder.y])
                    v_up = np.array([0, -1])
                    unit_v1 = v1 / (np.linalg.norm(v1) + 1e-6)
                    target_shoulder = int(np.degrees(np.arccos(np.clip(np.dot(unit_v1, v_up), -1.0, 1.0))) - 90)

                    v_arm = np.array([j_shoulder.x - j_elbow.x, j_shoulder.y - j_elbow.y])
                    v_forearm = np.array([j_wrist.x - j_elbow.x, j_wrist.y - j_elbow.y])
                    unit_arm = v_arm / (np.linalg.norm(v_arm) + 1e-6)
                    unit_forearm = v_forearm / (np.linalg.norm(v_forearm) + 1e-6)
                    target_elbow = int(180 - np.degrees(np.arccos(np.clip(np.dot(unit_arm, unit_forearm), -1.0, 1.0))))

                    # Base rotation multiplier
                    dy_normalized = (j_wrist.y - j_shoulder.y) * 4
                    target_base = int(np.clip(dy_normalized * 90, -90, 90))

                    # 2. Hand Logic Layer: Extract J3, J4, J5
                    target_j3 = current_angles[3]
                    target_j4 = current_angles[4]
                    target_j5 = current_angles[5]

                    if hand_landmarks_list:
                        hand_lms = hand_landmarks_list[0]
                        # Landmarks
                        wrist = hand_lms[0]
                        index_mcp = hand_lms[5]
                        middle_mcp = hand_lms[9]
                        pinky_mcp = hand_lms[17]
                        thumb_tip = hand_lms[4]
                        index_tip = hand_lms[8]

                        # --- J3: Palm Rotation (Roll) ---
                        # Invert y because image coordinates go from top to bottom
                        dx = pinky_mcp.x - index_mcp.x
                        dy = pinky_mcp.y - index_mcp.y
                        roll_angle = np.degrees(np.arctan2(dy, dx))
                        # Center around 0 and map to [-90, 90]
                        target_j3 = int(np.clip(roll_angle * 2, -90, 90))

                        # --- J4: Hand Depth (Back/Forward) ---
                        # Proxy: distance between wrist and middle MCP
                        hand_size = np.sqrt((middle_mcp.x - wrist.x)**2 + (middle_mcp.y - wrist.y)**2)
                        # Assume 0.1 is far (-90) and 0.3 is close (90)
                        # This may need calibration
                        depth_norm = np.clip((hand_size - 0.1) / (0.3 - 0.1), 0.0, 1.0)
                        target_j4 = int(depth_norm * 180 - 90)

                        # --- J5: Gripper (Thumb-Index distance) ---
                        pinch_dist = np.sqrt((index_tip.x - thumb_tip.x)**2 + (index_tip.y - thumb_tip.y)**2)
                        # Normalize by hand size to be scale-invariant
                        pinch_ratio = pinch_dist / (hand_size + 1e-6)
                        # Closed if ratio < 0.2, open if ratio > 0.8
                        gripper_norm = np.clip((pinch_ratio - 0.2) / (0.8 - 0.2), 0.0, 1.0)
                        # Map to [-90, 90] (assuming 90 is open)
                        target_j5 = int(gripper_norm * 180 - 90)

                        # Drawing Hand skeleton
                        for pair in [(0,1), (0,5), (5,9), (9,13), (13,17), (0,17), (1,2), (2,3), (3,4), 
                                     (5,6), (6,7), (7,8), (9,10), (10,11), (11,12), (13,14), (14,15), (15,16), (17,18), (18,19), (19,20)]:
                            p1 = (int(hand_lms[pair[0]].x * w_f), int(hand_lms[pair[0]].y * h_f))
                            p2 = (int(hand_lms[pair[1]].x * w_f), int(hand_lms[pair[1]].y * h_f))
                            cv2.line(frame, p1, p2, (0, 255, 255), 1)
                        for lm in hand_lms:
                            cx, cy = int(lm.x * w_f), int(lm.y * h_f)
                            cv2.circle(frame, (cx, cy), 3, (255, 0, 0), cv2.FILLED)

                    # Update targets
                    targets = [
                        -target_base, 
                        -target_shoulder, 
                        -target_elbow,
                        target_j3, 
                        target_j4, 
                        target_j5
                    ]
                    
                    # Smoothing and persistence
                    EMA_ALPHA = 0.2
                    MAX_STEP = 10.0
                    
                    if not self.camera_active_last_frame:
                         self.smooth_camera_angles = [float(t) for t in targets]
                         self.camera_active_last_frame = True

                    for i in range(6):
                        diff = targets[i] - self.smooth_camera_angles[i]
                        step = np.clip(diff, -MAX_STEP, MAX_STEP)
                        self.smooth_camera_angles[i] = (self.smooth_camera_angles[i] + step) * EMA_ALPHA + \
                                                       self.smooth_camera_angles[i] * (1 - EMA_ALPHA)

                    current_angles = [int(a) for a in self.smooth_camera_angles]
                    
                    # 2. Drawing Pose Skeleton
                    pts = []
                    for lm in [j_shoulder, j_elbow, j_wrist]:
                        cx, cy = int(lm.x * w_f), int(lm.y * h_f)
                        pts.append((cx, cy))
                        cv2.circle(frame, (cx, cy), 6, (0, 255, 0), cv2.FILLED)
                    cv2.line(frame, pts[0], pts[1], (255, 255, 0), 2)
                    cv2.line(frame, pts[1], pts[2], (255, 255, 0), 2)
                    
                except Exception as e:
                    print(f"Error en CameraProcessorMixin: {e}")

        return frame, current_angles, arm_visible, low_confidence


    def get_camera_status_ui(self, is_playing, arm_visible, low_confidence):
        """Returns the status message and style based on current tracking state."""
        if is_playing:
            status_msg = "SISTEMA: REPRODUCIENDO ANIMACIÓN"
            status_style = "background-color: #fbc02d; color: #000000; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
        elif arm_visible:
            status_msg = "SISTEMA: SEGUIMIENTO ACTIVO"
            status_style = "background-color: #1b5e20; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
        elif low_confidence:
            status_msg = "SISTEMA: BAJA CONFIANZA"
            status_style = "background-color: #e65100; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
        else:
            status_msg = "SISTEMA: NO DETECTADO"
            status_style = "background-color: #b71c1c; color: #ffffff; font-weight: bold; font-size: 11px; padding: 2px; border-radius: 2px;"
            
        return status_msg, status_style
