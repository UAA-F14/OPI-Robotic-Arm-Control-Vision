"""Control del brazo EX2BrazoPS4 copiando tu propio brazo (izquierdo o
derecho, el que la camara vea mejor), usando el celular como camara (app
"IP Webcam") y dos modelos chicos de MediaPipe (PoseLandmarker lite +
HandLandmarker) para ubicar hombro, codo, muneca y la mano abierta/cerrada.

Se usan dos modelos por separado en vez del Holistic de MediaPipe porque
Holistic siempre calcula tambien la cara (nunca la usamos) y en el CPU de
la Orange eso sobraba y hacia todo lento.

Mapeo 1:1, facil de explicar en la expo -- cada servo copia una
articulacion real de tu brazo:
  - Angulo del HOMBRO  (cadera-hombro-codo)            -> servo X
  - Angulo del CODO    (hombro-codo-muneca)             -> servo Y
  - Giro de la MUNECA  (direccion muneca -> palma)      -> servo D-pad
  - Pellizco pulgar-indice (abrir/cerrar la mano)       -> servo de la pinza

Parate de forma que la camara del celular te vea desde la cadera hasta
la mano -- si no se ve la cadera no se puede calcular el angulo del
hombro. Hay que correr este script con sudo (para los canales PWM).

Logica repartida en archivos aparte:
  - geometry.py    -- matematicas puras (angulos, cual brazo seguir).
  - drawing.py     -- dibuja el esqueleto encima del frame.
  - pwm_servo.py   -- control de cada servo por PWM.
  - web_preview.py -- la paginita web para ver el video en vivo.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from geometry import clamp, joint_angle_deg, wrist_turn_deg, pinch_ratio, pick_arm
from drawing import draw_arm_skeleton, draw_hand_skeleton
from pwm_servo import Servo, SERVO_X_CHANNEL, SERVO_Y_CHANNEL, SERVO_GRIP_CHANNEL, SERVO_DPAD_CHANNEL
from web_preview import start_preview_server, publish_preview_frame, FrameGrabber, HTTP_PORT

STREAM_URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.50:8080/video"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
POSE_MODEL_PATH = os.path.join(PROJECT_DIR, "models", "pose_landmarker_lite.task")
HAND_MODEL_PATH = os.path.join(PROJECT_DIR, "models", "hand_landmarker.task")

# Rango de giro de muneca (grados, direccion muneca->palma en el plano
# de la imagen) que se mapea a 0..180 del servo. Ajustar a ojo viendo
# los valores que se ven en la pagina web.
WRIST_DEG_MIN, WRIST_DEG_MAX = -90.0, 90.0

# Suavizado exponencial: entre mas chico, mas suave pero mas lento.
SMOOTHING = 0.3

# Tope de frames por segundo a procesar. Mas de esto no se nota a simple
# vista (nadie mueve el brazo tan rapido) y asi el CPU no esta al 100%
# todo el tiempo -- genera menos calor mientras la Orange no tiene disipador.
TARGET_FPS = 10.0
MIN_FRAME_SECONDS = 1.0 / TARGET_FPS


def main():
    servo_x = Servo(SERVO_X_CHANNEL)
    servo_y = Servo(SERVO_Y_CHANNEL)
    servo_grip = Servo(SERVO_GRIP_CHANNEL)
    servo_dpad = Servo(SERVO_DPAD_CHANNEL)

    pose_landmarker = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
        )
    )
    hand_landmarker = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=HAND_MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
        )
    )

    start_preview_server()
    print(f"Vista en vivo en http://<ip-de-la-orange>:{HTTP_PORT}/")

    # Cuerpo y mano se detectan al mismo tiempo en dos hilos -- cada modelo
    # usa nucleos distintos del CPU, asi que no se espera a que termine
    # uno para empezar el otro (antes salian uno tras otro en el mismo hilo).
    executor = ThreadPoolExecutor(max_workers=2)

    angle_shoulder, angle_elbow, angle_wrist, angle_grip = 90.0, 90.0, 90.0, 90.0
    grabber = None
    start_ms = time.monotonic() * 1000
    fps_count, fps_t0 = 0, time.monotonic()

    try:
        grabber = FrameGrabber(STREAM_URL)
        if not grabber.running:
            print(f"No se pudo abrir el stream: {STREAM_URL}")
            return

        while True:
            loop_start = time.monotonic()

            if not grabber.running:
                print("Se perdio el stream de la camara.")
                break

            frame = grabber.read()
            if frame is None:
                time.sleep(0.01)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int(time.monotonic() * 1000 - start_ms)
            pose_future = executor.submit(pose_landmarker.detect_for_video, mp_image, timestamp_ms)
            hand_future = executor.submit(hand_landmarker.detect_for_video, mp_image, timestamp_ms)
            pose_result = pose_future.result()
            hand_result = hand_future.result()

            pose = pose_result.pose_landmarks[0] if pose_result.pose_landmarks else None
            arm_label = "NO"

            if hand_result.hand_landmarks:
                hand = hand_result.hand_landmarks[0]
                # category_name viene en ingles: "Left"/"Right".
                hand_label = hand_result.handedness[0][0].category_name[:3].upper()
            else:
                hand, hand_label = None, "NO"

            if pose:
                hip, shoulder, elbow, wrist, arm_label = pick_arm(pose)
                draw_arm_skeleton(frame, hip, shoulder, elbow, wrist)

                shoulder_target = joint_angle_deg(hip, shoulder, elbow)
                elbow_target = joint_angle_deg(shoulder, elbow, wrist)
                if shoulder_target is not None:
                    angle_shoulder += (shoulder_target - angle_shoulder) * SMOOTHING
                    servo_x.set_angle(angle_shoulder)
                if elbow_target is not None:
                    angle_elbow += (elbow_target - angle_elbow) * SMOOTHING
                    servo_y.set_angle(angle_elbow)

                if hand:
                    draw_hand_skeleton(frame, hand)

                    wrist_deg = wrist_turn_deg(wrist, hand[9])
                    if wrist_deg is not None:
                        wrist_target = clamp(
                            (wrist_deg - WRIST_DEG_MIN) / (WRIST_DEG_MAX - WRIST_DEG_MIN) * 180.0,
                            0.0,
                            180.0,
                        )
                        angle_wrist += (wrist_target - angle_wrist) * SMOOTHING
                        servo_dpad.set_angle(angle_wrist)

                    grip_target = (1.0 - pinch_ratio(hand)) * 180.0  # pellizcado = cerrada
                    angle_grip += (grip_target - angle_grip) * SMOOTHING
                    servo_grip.set_angle(angle_grip)

            # tamano de letra proporcional al ancho del frame, para que
            # nunca se salga del cuadro sin importar la resolucion
            font_scale = clamp(frame.shape[1] / 1600.0, 0.4, 0.8)
            line_h = int(30 * font_scale)
            for i, line in enumerate((
                f"HOMBRO={angle_shoulder:5.1f} CODO={angle_elbow:5.1f} BRAZO={arm_label}",
                f"MUNECA={angle_wrist:5.1f} PINZA={angle_grip:5.1f} MANO={hand_label}",
            )):
                cv2.putText(
                    frame, line, (10, line_h * (i + 1)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 0), 2,
                )
            publish_preview_frame(frame)

            fps_count += 1
            if time.monotonic() - fps_t0 >= 2.0:
                print(f"loop real: {fps_count / (time.monotonic() - fps_t0):.1f} FPS")
                fps_count, fps_t0 = 0, time.monotonic()

            elapsed = time.monotonic() - loop_start
            if elapsed < MIN_FRAME_SECONDS:
                time.sleep(MIN_FRAME_SECONDS - elapsed)
    finally:
        executor.shutdown(wait=False)
        if grabber is not None:
            grabber.release()
        pose_landmarker.close()
        hand_landmarker.close()
        servo_x.close()
        servo_y.close()
        servo_grip.close()
        servo_dpad.close()


if __name__ == "__main__":
    main()
