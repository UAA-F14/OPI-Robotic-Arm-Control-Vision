# code/

- `hand_arm_control.py` -- entry point. Wires everything together: reads
  the camera, runs both MediaPipe models, computes the 4 servo angles,
  and drives the main loop.
- `geometry.py` -- pure math: joint angles, which arm (left/right) to
  track, pinch ratio for the gripper. No OpenCV, no hardware.
- `drawing.py` -- draws the arm/hand skeleton on top of the video frame.
- `pwm_servo.py` -- `Servo` class, talks to `/sys/class/pwm/pwmchip0`
  directly (same channels/period as the original `pwm.c`, rewritten in
  Python so nothing needs to be compiled). Runs in a simulated mode with
  no hardware present, so the rest of the pipeline can be tested on a
  regular laptop. The real channel-to-joint mapping (base/shoulder/elbow/
  gripper) was confirmed by hand, moving each PWM channel on its own --
  it doesn't match the original guesswork comments. The gripper servo is
  a continuous-rotation (360) type, so it's driven at full speed in one
  direction instead of to a fixed angle.
- `web_preview.py` -- the self-hosted MJPEG page (port 5000) used to
  watch the live video with the skeleton drawn on top, no X11/VNC needed.
- `requirements.txt` -- Python dependencies.
- `models/` -- the two MediaPipe `.task` files go here (see the main
  readme for the download links). Not committed to the repo due to size.
