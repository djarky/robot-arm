"""
gui/camera_thread.py — Background camera capture + MediaPipe inference thread.

Classes:
    CameraThread — QThread that reads from camera and runs dual MediaPipe landmarkers
                   (Pose + Hands), emitting processed frames via image_update signal.
"""
import cv2
import numpy as np
import mediapipe as mp
from PySide6.QtCore import QThread, Signal


class CameraThread(QThread):
    """Captures camera frames and runs MediaPipe Pose + Hand landmarkers.

    Signals:
        image_update(np.ndarray, list, list): Emits (frame, pose_landmarks_list, hand_landmarks_list).
    """

    image_update = Signal(np.ndarray, list, list)

    def __init__(self):
        super().__init__()
        self.running = True
        self.pose_model = "pose_landmarker.task"
        self.hand_model = "hand_landmarker.task"

    def run(self):
        BaseOptions = mp.tasks.BaseOptions

        # Pose landmarker
        PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions

        # Hand landmarker
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions

        VisionRunningMode = mp.tasks.vision.RunningMode

        pose_options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.pose_model),
            running_mode=VisionRunningMode.IMAGE,
        )
        hand_options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=self.hand_model),
            running_mode=VisionRunningMode.IMAGE,
            num_hands=1,
        )

        cap = cv2.VideoCapture(0)
        with (
            PoseLandmarker.create_from_options(pose_options) as pose_landmarker,
            HandLandmarker.create_from_options(hand_options) as hand_landmarker,
        ):
            while self.running:
                success, frame = cap.read()
                if success:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

                    pose_result = pose_landmarker.detect(mp_image)
                    hand_result = hand_landmarker.detect(mp_image)

                    pose_lms = pose_result.pose_landmarks if pose_result.pose_landmarks else []
                    hand_lms = hand_result.hand_landmarks if hand_result.hand_landmarks else []

                    self.image_update.emit(frame, pose_lms, hand_lms)
                else:
                    self.msleep(30)
        cap.release()

    def stop(self):
        self.running = False
        self.wait()
