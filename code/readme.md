# code/

- `hand_arm_control.py` -- main script. Reads the camera stream, runs
  MediaPipe's `PoseLandmarker` + `HandLandmarker`, computes the 4 angles
  (shoulder, elbow, wrist, gripper) and drives the servos over PWM. It
  also hosts its own web page (port 5000) to watch the live video with
  the skeleton drawn on top.
- `requirements.txt` -- Python dependencies.
- `models/` -- the two MediaPipe `.task` files go here (see the main
  readme for the download links). Not committed to the repo due to size.

If run on a machine without the Orange Pi's PWM channels (for example to
test detection on a laptop), the script detects that on its own and
simulates the servos instead of crashing.
