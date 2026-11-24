"""Dibuja el esqueleto del brazo y la mano sobre el frame, con OpenCV."""
import cv2

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
    """landmark.x/.y vienen normalizados 0..1 de MediaPipe -- hay que
    escalarlos al tamaño real del frame antes de dibujar."""
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
    """Dibuja los 21 puntos de la mano y sus conexiones, mas una linea
    amarilla pulgar-indice aparte -- esa es la que de verdad mueve la
    pinza (ver pinch_ratio en geometry.py), por eso se resalta distinto
    al resto del esqueleto."""
    for a, b in HAND_CONNECTIONS:
        draw_line(frame, hand_landmarks[a], hand_landmarks[b])
    for point in hand_landmarks:
        draw_point(frame, point, radius=3)
    draw_line(frame, hand_landmarks[4], hand_landmarks[8], color=(0, 255, 255), thickness=2)
