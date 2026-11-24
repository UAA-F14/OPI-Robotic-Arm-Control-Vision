# OPI Robotic Arm Control Vision

Real-time control of the EX2BrazoPS4 robotic arm (Orange Pi 4 Pro) by
copying a person's right arm, using a phone as the camera and MediaPipe
for pose/hand detection. No glove, no sensors, no physical controller --
the camera watches the arm and the robot copies it.

## How it works

An Android phone (app "IP Webcam") streams video over USB to the Orange
Pi. Two small MediaPipe models run in parallel on every frame:

- `PoseLandmarker` (lite) -- locates hip, shoulder, elbow and wrist.
- `HandLandmarker` -- locates the 21 hand points, to tell if the hand is
  open or closed.

Those points are used to compute 4 angles, one per servo:

| Real joint                     | How it's computed                          | Servo         |
|---------------------------------|---------------------------------------------|---------------|
| Shoulder                        | angle at hip-shoulder-elbow                  | Servo X       |
| Elbow                           | angle at shoulder-elbow-wrist                | Servo Y       |
| Base rotation                   | torso/shoulder-line rotation                 | Servo D-pad   |
| Open/closed hand (gripper)      | thumb-index distance (pinch), sent binary     | Servo gripper |

The arm doesn't have a wrist joint -- it has a base rotation instead,
confirmed by moving each PWM channel by hand. The gripper servo is a
360-degree continuous-rotation type (the pulse sets speed/direction, not
a fixed position), so its signal is sent as a binary full-speed command
in one direction or the other instead of a smoothed intermediate angle --
it's expected to stall safely against its own mechanical limit.

The system automatically picks whichever arm (left or right) the camera
is seeing best (whichever side has more visible landmarks), so you
don't have to tell it which arm you're using. The result can be
watched live from any browser on the same network, no monitor or cable
needed on the Orange Pi itself.

## Hardware

- Orange Pi 4 Pro (RK3588) -- runs detection and drives the servos via
  sysfs PWM (`/sys/class/pwm/pwmchip0`), same as the original PS4
  controller version of this arm.
- EX2BrazoPS4 arm, 4 servos (shoulder, elbow, base rotation, gripper).
- Android phone running the **IP Webcam** app, connected to the Orange Pi
  with a USB cable (faster and more stable than wifi).
- The RK3588 gets quite hot running the models non-stop -- a heatsink
  (even a small one, with thermal paste) is recommended.

## Setup

```bash
cd code
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Download the two MediaPipe models (not included in the repo due to size):

```bash
mkdir -p models
curl -o models/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
curl -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

## Connecting the camera over USB

1. Connect the phone to the Orange Pi with a USB cable, with **USB
   debugging** enabled (Settings -> Developer options) and authorized.
2. Open **IP Webcam** on the phone and tap "Start server".
3. On the Orange Pi:

```bash
sudo apt install android-tools-adb
sudo adb forward tcp:8080 tcp:8080
```

This makes the camera stream readable from `http://127.0.0.1:8080/video`
directly on the Orange Pi, without going through wifi.

## Running the arm control

The script needs root to write the PWM channels:

```bash
sudo venv/bin/python code/hand_arm_control.py http://127.0.0.1:8080/video
```

On startup it prints the live view address, something like:

```
Live view at http://<orange-pi-ip>:5000/
```

That page shows the video with the arm/hand skeleton drawn on top and
the 4 live angles -- useful for calibration and for the demo, with no
screen attached to the Orange Pi.

Stand so the camera sees you from your hip to your hand -- without the
hip in frame, the shoulder angle can't be computed.

### Calibration

Two things in `code/geometry.py` were tuned by hand against real
camera readings, not guessed, and may need re-tuning for a different
phone/lighting/distance:

- `PINCH_CLOSED` / `PINCH_OPEN` -- the normalized thumb-to-index
  distance (relative to the hand's own size) that counts as a fully
  closed or fully open hand. Too narrow a gap makes the gripper twitchy
  between the two extremes; too wide and it never reaches either one.
- `BASE_ROT_MIN` / `BASE_ROT_MAX` (in `code/hand_arm_control.py`) --
  the torso-rotation angle range mapped to the base servo's 0-180.

## Troubleshooting

- **`adb devices` shows the phone but with "no permissions"** -- run
  `adb` as root instead (`sudo adb kill-server && sudo adb devices -l
  && sudo adb forward tcp:8080 tcp:8080`). The Orange Pi's udev rules
  don't grant the regular user access to this specific phone's USB
  vendor/product ID.
- **Phone shows a second USB-debugging authorization popup** -- normal
  the first time `adb` runs as root, since root is a different "host"
  than the one you already authorized as a regular user. Accept it too.
- **Camera stream times out (`http://127.0.0.1:8080/video` doesn't
  respond)** -- make sure "IP Webcam" is open and its server was
  started (tap "Start server" in the app), and that the `adb forward`
  above is still active -- it drops if `adb` restarts.

## Performance notes

- Body and hand detection run in parallel (two threads), not one after
  the other.
- The main loop is capped at 10 FPS on purpose -- that's more than
  enough for the arm to look smooth, and keeps the CPU from running at
  100% all the time (less heat).
- Without a heatsink, the RK3588's thermal protection quietly throttles
  the clock speed to avoid overheating -- even a small heatsink makes it
  run noticeably faster.

## Team

- Camera & connectivity: Rafael De Luna
- Pose detection & math: DasReyxr
- Servos & hardware: Kevin Lara
- Visualization & integration: IKGB105
- Documentation: Janna

## References

- [MediaPipe Pose Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) -- docs for the body pose model.
- [MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker) -- docs for the hand model.
- [MediaPipe model index](https://storage.googleapis.com/mediapipe-models) -- where `.task` model files are hosted.
- [IP Webcam (Android app)](https://play.google.com/store/apps/details?id=com.pas.webcam) -- turns the phone into a camera server.
- [Android Debug Bridge (adb)](https://developer.android.com/tools/adb) -- used for `adb forward` over USB.
- [Linux PWM sysfs interface](https://www.kernel.org/doc/html/latest/driver-api/pwm.html) -- how `pwm_servo.py` talks to the servos.
