import Jetson.GPIO as GPIO
import time


class Servo:
    def __init__(
        self,
        pin,
        frequency=50,
        min_duty=2.5,
        max_duty=12.5,
        min_angle=0.0,
        max_angle=180.0
    ):
        self.pin = pin
        self.frequency = frequency
        self.min_duty = min_duty
        self.max_duty = max_duty
        self.min_angle = min_angle
        self.max_angle = max_angle

        GPIO.setup(self.pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, self.frequency)
        self.pwm.start(0.0)

    def angle_to_duty(self, angle):
        angle = max(self.min_angle, min(self.max_angle, angle))
        span_angle = self.max_angle - self.min_angle
        span_duty = self.max_duty - self.min_duty
        duty = self.min_duty + (angle - self.min_angle) * span_duty / span_angle
        return duty

    def set_angle(self, angle):
        duty = self.angle_to_duty(angle)
        self.pwm.ChangeDutyCycle(duty)
        time.sleep(0.02)

    def stop(self):
        self.pwm.ChangeDutyCycle(0.0)

    def cleanup(self):
        self.pwm.stop()
