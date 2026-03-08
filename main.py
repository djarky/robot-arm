import cv2
import mediapipe as mp
import time
import numpy as np

# Configuración de MediaPipe Tasks
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

def main():
    model_path = 'hand_landmarker.task'

    # Opciones de detección
    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=VisionRunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: No se pudo abrir la cámara.")
        return

    print("Iniciando seguimiento de manos (Tasks API). Presiona 'q' para salir.")

    # Conexiones de la mano (definidas manualmente para dibujo)
    HAND_CONNECTIONS = [
        (0, 1), (1, 2), (2, 3), (3, 4),           # Pulgar
        (0, 5), (5, 6), (6, 7), (7, 8),           # Índice
        (0, 9), (9, 10), (10, 11), (11, 12),      # Medio
        (0, 13), (13, 14), (14, 15), (15, 16),    # Anular
        (0, 17), (17, 18), (18, 19), (19, 20),    # Meñique
        (5, 9), (9, 13), (13, 17)                 # Palma
    ]

    with HandLandmarker.create_from_options(options) as landmarker:
        p_time = 0
        while True:
            success, frame = cap.read()
            if not success:
                break

            # MediaPipe necesita la imagen en RGB (OpenCV lee en BGR)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            # Detección
            result = landmarker.detect(mp_image)

            # Dibujo manual de landmarks y conexiones
            if result.hand_landmarks:
                for hand_lms in result.hand_landmarks:
                    h, w, _ = frame.shape
                    
                    # Dibujar conexiones
                    for connection in HAND_CONNECTIONS:
                        start_idx = connection[0]
                        end_idx = connection[1]
                        
                        start_lm = hand_lms[start_idx]
                        end_lm = hand_lms[end_idx]
                        
                        start_point = (int(start_lm.x * w), int(start_lm.y * h))
                        end_point = (int(end_lm.x * w), int(end_lm.y * h))
                        
                        cv2.line(frame, start_point, end_point, (0, 255, 0), 2)

                    # Dibujar puntos
                    for landmark in hand_lms:
                        cx, cy = int(landmark.x * w), int(landmark.y * h)
                        cv2.circle(frame, (cx, cy), 5, (255, 0, 255), cv2.FILLED)

                    # --- Lógica de Reconocimiento de Gestos (Contar Dedos) ---
                    # Puntos de las puntas de los dedos: Pulgar(4), Indice(8), Medio(12), Anular(16), Meñique(20)
                    fingers = []
                    
                    # Pulgar (Lógica horizontal para detectar si está abierto) 
                    # Comparamos punta (4) con el nudillo anterior (3)
                    # Nota: Esto varía según si es mano izquierda o derecha, pero para una app básica:
                    if hand_lms[4].x < hand_lms[3].x: # Asumiendo mano derecha
                        fingers.append(1)
                    else:
                        fingers.append(0)

                    # Otros 4 dedos (Lógica vertical: punta arriba del nudillo)
                    for tip_id in [8, 12, 16, 20]:
                        if hand_lms[tip_id].y < hand_lms[tip_id - 2].y:
                            fingers.append(1)
                        else:
                            fingers.append(0)

                    total_fingers = fingers.count(1)
                    cv2.putText(frame, f'Dedos: {total_fingers}', (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            # Calcular FPS
            c_time = time.time()
            fps = 1 / (c_time - p_time) if (c_time - p_time) > 0 else 0
            p_time = c_time
            cv2.putText(frame, f'FPS: {int(fps)}', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

            # Mostrar resultado
            cv2.imshow("Hand Tracking (Modern API)", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
