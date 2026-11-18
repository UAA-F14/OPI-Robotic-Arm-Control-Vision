# OPI Robotic Arm Control Vision

Control del brazo robotico EX2BrazoPS4 (Orange Pi 4 Pro) copiando en tiempo
real el brazo derecho de una persona, usando el celular como camara y
deteccion de postura/mano con MediaPipe. Sin guante, sin sensores, sin
controles fisicos -- la camara ve el brazo y el robot lo copia.

## Como funciona

Un celular Android (app "IP Webcam") manda video por USB a la Orange Pi.
Dos modelos chicos de MediaPipe corren en paralelo sobre cada frame:

- `PoseLandmarker` (version lite) -- ubica cadera, hombro, codo y muneca.
- `HandLandmarker` -- ubica los 21 puntos de la mano, para saber si esta
  abierta o cerrada.

Con esos puntos se calculan 4 angulos, uno por cada servo del brazo:

| Articulacion real              | Como se calcula                          | Servo         |
|---------------------------------|-------------------------------------------|---------------|
| Hombro                          | angulo cadera-hombro-codo                  | Servo X       |
| Codo                            | angulo hombro-codo-muneca                  | Servo Y       |
| Giro de muneca                  | direccion muneca -> palma                  | Servo D-pad   |
| Mano abierta/cerrada (pinza)    | distancia pulgar-indice (pellizco)         | Servo pinza   |

El sistema detecta automaticamente cual de los dos brazos (izquierdo o
derecho) esta viendo mejor la camara, y usa ese. El resultado se puede ver
en vivo desde cualquier navegador en la misma red, sin necesitar cable ni
monitor conectado a la Orange.

## Hardware

- Orange Pi 4 Pro (RK3588) -- corre la deteccion y mueve los servos via
  PWM por sysfs (`/sys/class/pwm/pwmchip0`), igual que el control original
  por control de PS4 de este mismo brazo.
- Brazo EX2BrazoPS4, 4 servos (hombro, codo, muneca, pinza).
- Celular Android con la app **IP Webcam**, conectado por cable USB a la
  Orange Pi (mas rapido y estable que por wifi).
- El RK3588 calienta bastante corriendo los modelos sin parar -- se
  recomienda disipador (aunque sea uno chico con pasta termica).

## Instalacion

```bash
cd code
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Descargar los dos modelos de MediaPipe (no se incluyen en el repo por
tamano):

```bash
mkdir -p models
curl -o models/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
curl -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

## Conectar la camara por USB

1. Celular conectado a la Orange Pi con cable USB, con **Depuracion USB**
   activada (Ajustes -> Opciones de desarrollador) y autorizada.
2. Abrir **IP Webcam** en el celular y darle "Start server".
3. En la Orange Pi:

```bash
sudo apt install android-tools-adb
sudo adb forward tcp:8080 tcp:8080
```

Con esto el stream de la camara se puede leer desde `http://127.0.0.1:8080/video`
dentro de la propia Orange, sin pasar por wifi.

## Correr el control del brazo

El script necesita permisos de root para escribir los canales PWM:

```bash
sudo venv/bin/python code/hand_arm_control.py http://127.0.0.1:8080/video
```

Al arrancar imprime la direccion de la vista en vivo, algo como:

```
Vista en vivo en http://<ip-de-la-orange>:5000/
```

Esa pagina muestra el video con el esqueleto del brazo/mano dibujado
encima y los 4 angulos en tiempo real -- util para calibrar y para la
demo, sin necesitar pantalla conectada a la Orange.

Parate de forma que la camara te vea desde la cadera hasta la mano -- si
no ve la cadera no puede calcular el angulo del hombro.

## Notas de rendimiento

- La deteccion de cuerpo y mano corre en paralelo (dos hilos), no una
  despues de la otra.
- El loop esta topado a 10 FPS a proposito -- es mas que suficiente para
  que el brazo se vea fluido, y evita tener el CPU al 100% todo el
  tiempo (menos calor).
- Si el RK3588 esta sin disipador, el sistema de proteccion termica del
  kernel le baja la frecuencia solo para no sobrecalentarse -- con un
  disipador, aunque sea chico, corre notablemente mas rapido.
