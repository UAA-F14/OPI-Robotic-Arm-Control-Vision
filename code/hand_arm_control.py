"""Control del brazo EX2BrazoPS4 copiando tu propio brazo DERECHO, usando
el celular como camara (app "IP Webcam") y dos modelos chicos de MediaPipe
(PoseLandmarker lite + HandLandmarker) para ubicar hombro, codo, muneca y
la mano abierta/cerrada. Se usan dos modelos por separado en vez del
Holistic de MediaPipe porque Holistic siempre calcula tambien la cara
(nunca la usamos) y en el CPU de la Orange eso sobraba y hacia todo lento.

Mapeo 1:1, facil de explicar en la expo -- cada servo copia una
articulacion real de tu brazo:
  - Angulo del HOMBRO  (cadera-hombro-codo)            -> servo X
  - Angulo del CODO    (hombro-codo-muneca)             -> servo Y
  - Giro de la MUNECA  (direccion muneca -> palma)      -> servo D-pad
  - Pellizco pulgar-indice (abrir/cerrar la mano)       -> servo de la pinza

Parate de forma que la camara del celular te vea desde la cadera hasta
la mano del lado derecho -- si no se ve la cadera no se puede calcular
el angulo del hombro.

Vista en vivo: este script levanta su propia paginita web (sin Flask,
solo http.server) que transmite el video con los angulos encima. Se abre
en el navegador apuntando a la IP de Tailscale de la Orange, puerto 5000 --
nada de X11 ni SSH para ver el video, mucho mas ligero.

Control de PWM: escribe directo a sysfs (/sys/class/pwm/pwmchip0/...),
igual que pwm.c del proyecto original -- mismos canales, mismo periodo
de 20ms. Hay que correr este script con sudo.
"""
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

STREAM_URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.50:8080/video"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
POSE_MODEL_PATH = os.path.join(PROJECT_DIR, "models", "pose_landmarker_lite.task")
HAND_MODEL_PATH = os.path.join(PROJECT_DIR, "models", "hand_landmarker.task")

HTTP_PORT = 5000

PWM_CHIP = "/sys/class/pwm/pwmchip0"
SERVO_X_CHANNEL = 0     # hombro
SERVO_Y_CHANNEL = 3     # codo
SERVO_GRIP_CHANNEL = 2  # pinza
SERVO_DPAD_CHANNEL = 4  # muneca

SERVO_PERIOD_NS = 20_000_000  # 20 ms -> 50 Hz
ANGLE_MIN, ANGLE_MAX = 0.0, 180.0

# Rango de giro de muneca (grados, direccion muneca->palma en el plano
# de la imagen) que se mapea a 0..180 del servo. Ajustar a ojo viendo
# los valores que se ven en la pagina web.
WRIST_DEG_MIN, WRIST_DEG_MAX = -90.0, 90.0

# Que tan pellizcados/abiertos tienen que estar los dedos para
# considerar la pinza totalmente cerrada/abierta.
PINCH_CLOSED = 0.05
PINCH_OPEN = 0.35

# Suavizado exponencial: entre mas chico, mas suave pero mas lento.
SMOOTHING = 0.3

# Tope de frames por segundo a procesar. Mas de esto no se nota a simple
# vista (nadie mueve el brazo tan rapido) y asi el CPU no esta al 100%
# todo el tiempo -- genera menos calor mientras la Orange no tiene disipador.
TARGET_FPS = 10.0
MIN_FRAME_SECONDS = 1.0 / TARGET_FPS

# Indices de MediaPipe Pose. Se usa el brazo (izquierdo o derecho) que la
# camara vea mejor en cada momento -- no importa cual, el mapeo es el mismo.
RIGHT_HIP, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST = 24, 12, 14, 16
LEFT_HIP, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST = 23, 11, 13, 15


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def angle_to_duty_ns(angle_deg):
    angle_deg = clamp(angle_deg, ANGLE_MIN, ANGLE_MAX)
    pulse_ns = 1_000_000 + int(angle_deg / 180.0 * 1_000_000)  # 1ms..2ms
    return SERVO_PERIOD_NS - pulse_ns


class Servo:
    """Un canal PWM de /sys/class/pwm -- en Python para no depender de la
    libreria compilada en C del proyecto original.

    Si no hay chip PWM en esta maquina (ej. probando en la laptop en vez
    de en la Orange), opera en modo simulado: nada mas imprime el angulo
    en vez de escribirlo a sysfs."""

    def __init__(self, channel):
        self.channel = channel
        self.base_path = f"{PWM_CHIP}/pwm{channel}"
        self.available = os.path.isdir(PWM_CHIP)
        if not self.available:
            print(f"[simulado] no hay {PWM_CHIP} en esta maquina -- canal {channel} no se mueve de verdad")
            return
        try:
            with open(f"{PWM_CHIP}/export", "w") as f:
                f.write(str(channel))
            time.sleep(0.2)
        except OSError:
            pass  # ya estaba exportado
        self._write("period", SERVO_PERIOD_NS)
        self._write("enable", 1)

    def _write(self, name, value):
        with open(f"{self.base_path}/{name}", "w") as f:
            f.write(str(value))

    def set_angle(self, angle_deg):
        if not self.available:
            return
        self._write("duty_cycle", angle_to_duty_ns(angle_deg))

    def close(self):
        if not self.available:
            return
        try:
            self._write("enable", 0)
            with open(f"{PWM_CHIP}/unexport", "w") as f:
                f.write(str(self.channel))
        except OSError:
            pass


def pick_arm(pose):
    """Regresa (cadera, hombro, codo, muneca, etiqueta) del brazo -- izquierdo
    o derecho -- que la camara este viendo mejor en este frame."""
    def visibility(hip, shoulder, elbow, wrist):
        return sum((pose[i].visibility or 0.0) for i in (hip, shoulder, elbow, wrist))

    if visibility(RIGHT_HIP, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST) >= \
            visibility(LEFT_HIP, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST):
        hip, shoulder, elbow, wrist, label = RIGHT_HIP, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, "DER"
    else:
        hip, shoulder, elbow, wrist, label = LEFT_HIP, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, "IZQ"
    return pose[hip], pose[shoulder], pose[elbow], pose[wrist], label


def joint_angle_deg(a, b, c):
    """Angulo en el vertice b entre los segmentos b->a y b->c (0..180)."""
    v1x, v1y = a.x - b.x, a.y - b.y
    v2x, v2y = c.x - b.x, c.y - b.y
    mag1 = math.hypot(v1x, v1y)
    mag2 = math.hypot(v2x, v2y)
    if mag1 < 1e-6 or mag2 < 1e-6:
        return None
    cos_angle = clamp((v1x * v2x + v1y * v2y) / (mag1 * mag2), -1.0, 1.0)
    return math.degrees(math.acos(cos_angle))


def wrist_turn_deg(wrist, palm_center):
    """Direccion muneca->palma en el plano de la imagen, en grados."""
    dx = palm_center.x - wrist.x
    dy = palm_center.y - wrist.y
    if math.hypot(dx, dy) < 1e-6:
        return None
    return math.degrees(math.atan2(-dy, dx))


def hand_size(hand_landmarks):
    wrist = hand_landmarks[0]
    middle_mcp = hand_landmarks[9]
    return math.hypot(wrist.x - middle_mcp.x, wrist.y - middle_mcp.y)


def pinch_ratio(hand_landmarks):
    thumb_tip, index_tip = hand_landmarks[4], hand_landmarks[8]
    raw = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
    normalized = raw / max(hand_size(hand_landmarks), 1e-6)
    return clamp((normalized - PINCH_CLOSED) / (PINCH_OPEN - PINCH_CLOSED), 0.0, 1.0)


# Topologia estandar de los 21 puntos de la mano en MediaPipe (pares de
# indices que se conectan con una linea para dibujar el "esqueleto").
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),            # pulgar
    (0, 5), (5, 6), (6, 7), (7, 8),            # indice
    (5, 9), (9, 10), (10, 11), (11, 12),       # medio
    (9, 13), (13, 14), (14, 15), (15, 16),     # anular
    (13, 17), (17, 18), (18, 19), (19, 20),    # menique
    (0, 17),                                   # base de la palma
]


def draw_point(frame, landmark, color=(0, 255, 0), radius=5):
    h, w = frame.shape[:2]
    cv2.circle(frame, (int(landmark.x * w), int(landmark.y * h)), radius, color, -1)


def draw_line(frame, a, b, color=(0, 255, 0), thickness=2):
    h, w = frame.shape[:2]
    cv2.line(frame, (int(a.x * w), int(a.y * h)), (int(b.x * w), int(b.y * h)), color, thickness)


def draw_arm_skeleton(frame, hip, shoulder, elbow, wrist):
    draw_line(frame, hip, shoulder)
    draw_line(frame, shoulder, elbow)
    draw_line(frame, elbow, wrist)
    for point in (hip, shoulder, elbow, wrist):
        draw_point(frame, point)


def draw_hand_skeleton(frame, hand_landmarks):
    for a, b in HAND_CONNECTIONS:
        draw_line(frame, hand_landmarks[a], hand_landmarks[b])
    for point in hand_landmarks:
        draw_point(frame, point, radius=3)
    # linea amarilla pulgar-indice: asi se ve directo el pellizco que mueve la pinza
    draw_line(frame, hand_landmarks[4], hand_landmarks[8], color=(0, 255, 255), thickness=2)


_frame_lock = threading.Lock()
_latest_jpeg = None

_PAGE_HTML = (
    b"<html><body style='margin:0;background:#000'>"
    b"<img src='/video_feed' style='width:100%;height:auto;display:block'>"
    b"</body></html>"
)


def publish_preview_frame(frame):
    global _latest_jpeg
    # calidad baja a proposito -- el preview es solo para ver, no afecta
    # la deteccion, y asi pesa menos para mandarlo por la red.
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if ok:
        with _frame_lock:
            _latest_jpeg = buf.tobytes()


class _StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # sin esto imprime una linea por cada frame

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(_PAGE_HTML)))
            self.end_headers()
            self.wfile.write(_PAGE_HTML)
            return

        if self.path == "/video_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _frame_lock:
                        jpeg = _latest_jpeg
                    if jpeg is not None:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self.send_response(404)
        self.end_headers()


def start_preview_server():
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), _StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


class FrameGrabber:
    """Lee la camara en su propio hilo, sin parar, y solo se queda con el
    frame mas reciente. Si la deteccion tarda mas que la camara en mandar
    frames, se saltan los viejos en vez de acumularse en fila -- eso es lo
    que causaba que el video se viera "del pasado" aunque fuera fluido."""

    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        self.lock = threading.Lock()
        self.frame = None
        self.running = self.cap.isOpened()
        if self.running:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                self.running = False
                break
            with self.lock:
                self.frame = frame

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def release(self):
        self.running = False
        self.cap.release()


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
    print(f"Vista en vivo en http://<ip-tailscale-de-la-orange>:{HTTP_PORT}/")

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
