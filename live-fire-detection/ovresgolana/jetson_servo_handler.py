import time
import Jetson.GPIO as GPIO

# Use a PWM-capable header pin that you've already enabled in jetson-io.
# On many Orin Nano setups, BOARD 33 is the one people use successfully for PWM.
SERVO_PIN = 33

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(SERVO_PIN, GPIO.OUT)

# SG90-style servo control is typically 50 Hz
pwm = GPIO.PWM(SERVO_PIN, 50)

def angle_to_duty(angle: float,
                  min_us: float = 500.0,
                  max_us: float = 2500.0,
                  freq: float = 50.0) -> float:
    """
    Convert angle in degrees (0-180) to PWM duty cycle percentage.
    """
    angle = max(0.0, min(180.0, angle))
    pulse_us = min_us + (angle / 180.0) * (max_us - min_us)
    period_us = 1000000.0 / freq
    return 100.0 * pulse_us / period_us

try:
    pwm.start(angle_to_duty(0))
    time.sleep(0.5)

    while True:
        for pos in range(0, 181):
            pwm.ChangeDutyCycle(angle_to_duty(pos))
            time.sleep(0.035)   # ~35 ms like your ESP8266 sketch

        for pos in range(180, -1, -1):
            pwm.ChangeDutyCycle(angle_to_duty(pos))
            time.sleep(0.035)

except KeyboardInterrupt:
    pass

finally:
    pwm.stop()
    GPIO.cleanup()
