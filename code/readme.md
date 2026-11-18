# code/

- `hand_arm_control.py` -- script principal. Lee el stream de la camara,
  corre `PoseLandmarker` + `HandLandmarker` de MediaPipe, calcula los 4
  angulos (hombro, codo, muneca, pinza) y mueve los servos por PWM. Levanta
  tambien su propia pagina web (puerto 5000) para ver el video en vivo con
  el esqueleto dibujado encima.
- `requirements.txt` -- dependencias de Python.
- `models/` -- aqui van los dos archivos `.task` de MediaPipe (ver el
  readme principal para el link de descarga). No se suben al repo por
  tamano.

Si se corre en una maquina sin los canales PWM de la Orange (por ejemplo
para probar nada mas la deteccion en una laptop), el script lo detecta
solo y simula los servos sin tronar.
