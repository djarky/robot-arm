import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

class CameraProcessorMixin:
    """Mixin that handles pose estimation logic, smoothing, and status for the camera tracking."""

    def process_pose_data(self, frame, pose_landmarks_list, is_playing):
        """
        Extracts joint angles from pose landmarks, applies smoothing (EMA),
        and draws the skeleton on the frame.
        
        Returns: (processed_frame, angles, arm_visible, low_confidence)
        """
        h_f, w_f, _ = frame.shape
        
        # Default angles if no detection (persistence)
        base_angle = self.smooth_camera_angles[0]
        shoulder_angle = self.smooth_camera_angles[1]
        elbow_angle = self.smooth_camera_angles[2]
        
        arm_visible = False
        low_confidence = False
        
        # 1. Logic Layer: Extract data
        if not is_playing and pose_landmarks_list:
            for pose_lms in pose_landmarks_list:
                try:
                    j_shoulder = pose_lms[12]
                    j_elbow = pose_lms[14]
                    j_wrist = pose_lms[16]
                    
                    # Validation
                    threshold = 0.5
                    if (j_shoulder.visibility < threshold or 
                        j_elbow.visibility < threshold or 
                        j_wrist.visibility < threshold):
                        low_confidence = True
                        continue
                    
                    arm_visible = True

                    # Calculate target angles...
                    v1 = np.array([j_elbow.x - j_shoulder.x, j_elbow.y - j_shoulder.y])
                    v_up = np.array([0, -1])
                    unit_v1 = v1 / (np.linalg.norm(v1) + 1e-6)
                    target_shoulder = int(np.degrees(np.arccos(np.clip(np.dot(unit_v1, v_up), -1.0, 1.0))) - 90)

                    v_arm = np.array([j_shoulder.x - j_elbow.x, j_shoulder.y - j_elbow.y])
                    v_forearm = np.array([j_wrist.x - j_elbow.x, j_wrist.y - j_elbow.y])
                    unit_arm = v_arm / (np.linalg.norm(v_arm) + 1e-6)
                    unit_forearm = v_forearm / (np.linalg.norm(v_forearm) + 1e-6)
                    target_elbow = int(180 - np.degrees(np.arccos(np.clip(np.dot(unit_arm, unit_forearm), -1.0, 1.0))))

                    # Increase multiplier (from 2 to 4) to make it more sensitive
                    dy_normalized = (j_wrist.y - j_shoulder.y) * 4
                    target_base = int(np.clip(dy_normalized * 90, -90, 90))

                    # Apply smoothing and Invert Angles
                    MAX_STEP = 10.0
                    EMA_ALPHA = 0.2
                    # Inverting all angles by negating them
                    targets = [-target_base, -target_shoulder, -target_elbow]
                    
                    if not self.camera_active_last_frame:
                         self.smooth_camera_angles = [float(t) for t in targets]
                         self.camera_active_last_frame = True

                    for i in range(3):
                        diff = targets[i] - self.smooth_camera_angles[i]
                        step = np.clip(diff, -MAX_STEP, MAX_STEP)
                        self.smooth_camera_angles[i] = (self.smooth_camera_angles[i] + step) * EMA_ALPHA + \
                                                       self.smooth_camera_angles[i] * (1 - EMA_ALPHA)

                    base_angle, shoulder_angle, elbow_angle = [int(a) for a in self.smooth_camera_angles]
                    
                    # 2. Drawing Layer: Skeleton
                    pts = []
                    for lm in [j_shoulder, j_elbow, j_wrist]:
                        cx, cy = int(lm.x * w_f), int(lm.y * h_f)
                        pts.append((cx, cy))
                        cv2.circle(frame, (cx, cy), 6, (0, 255, 0), cv2.FILLED)
                    cv2.line(frame, pts[0], pts[1], (255, 255, 0), 2)
                    cv2.line(frame, pts[1], pts[2], (255, 255, 0), 2)
                    
                except Exception as e:
                    print(f"Error en CameraProcessorMixin: {e}")

        return frame, [base_angle, shoulder_angle, elbow_angle], arm_visible, low_confidence

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
