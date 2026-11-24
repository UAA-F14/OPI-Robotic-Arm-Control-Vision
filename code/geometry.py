"""Matematicas puras: angulos de articulaciones, medidas de la mano, y
cual brazo seguir. Sin OpenCV ni nada de hardware -- solo numeros."""
import math

# Indices de MediaPipe Pose para los dos brazos. El que la camara vea
# mejor (izquierdo o derecho) se usa automaticamente -- ver pick_arm().
RIGHT_HIP, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST = 24, 12, 14, 16
LEFT_HIP, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST = 23, 11, 13, 15

# Que tan pellizcados/abiertos tienen que estar los dedos para
# considerar la pinza totalmente cerrada/abierta. Ajustar a ojo viendo
# el valor de PINZA en la vista en vivo.
PINCH_CLOSED = 0.75
PINCH_OPEN = 0.9


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


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


def shoulder_rotation_deg(pose):
    """Que tan girado (de lado) esta el torso, usando los dos hombros
    (11 y 12) y su profundidad (z) -- gira el torso hacia un lado y
    cambia, independiente de cual brazo este siguiendo pick_arm()."""
    left = pose[LEFT_SHOULDER]
    right = pose[RIGHT_SHOULDER]
    dx = right.x - left.x
    dz = right.z - left.z
    if math.hypot(dx, dz) < 1e-6:
        return None
    return math.degrees(math.atan2(dz, dx))


def hand_size(hand_landmarks):
    wrist = hand_landmarks[0]
    middle_mcp = hand_landmarks[9]
    return math.hypot(wrist.x - middle_mcp.x, wrist.y - middle_mcp.y)


def pinch_ratio(hand_landmarks):
    thumb_tip, index_tip = hand_landmarks[4], hand_landmarks[8]
    raw = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
    normalized = raw / max(hand_size(hand_landmarks), 1e-6)
    return clamp((normalized - PINCH_CLOSED) / (PINCH_OPEN - PINCH_CLOSED), 0.0, 1.0)
