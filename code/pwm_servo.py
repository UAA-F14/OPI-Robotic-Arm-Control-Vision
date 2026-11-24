"""Control de un servo por PWM via sysfs (/sys/class/pwm/pwmchip0/...),
igual que pwm.c del proyecto original pero reescrito en Python -- asi no
hay que compilar ni enlazar nada de C. Hay que correr con sudo."""
import os
import time

from geometry import clamp

PWM_CHIP = "/sys/class/pwm/pwmchip0"
SERVO_PERIOD_NS = 20_000_000  # 20 ms -> 50 Hz
ANGLE_MIN, ANGLE_MAX = 0.0, 180.0

# Canales de cada servo en el brazo EX2BrazoPS4 -- confirmados a mano
# moviendo cada canal por separado (el brazo no tiene muneca como eje
# fisico, tiene base; la señal de giro de muneca de la camara se manda
# ahi en su lugar).
SERVO_X_CHANNEL = 2     # hombro (sube/baja)
SERVO_Y_CHANNEL = 4     # codo
SERVO_GRIP_CHANNEL = 3  # pinza
SERVO_DPAD_CHANNEL = 0  # base (recibe la señal de giro de muneca)


def angle_to_duty_ns(angle_deg):
    angle_deg = clamp(angle_deg, ANGLE_MIN, ANGLE_MAX)
    pulse_ns = 1_000_000 + int(angle_deg / 180.0 * 1_000_000)  # 1ms..2ms
    return SERVO_PERIOD_NS - pulse_ns


class Servo:
    """Un canal PWM de /sys/class/pwm.

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
