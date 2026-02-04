import servo
import Jetson.GPIO as GPIO

class CameraMount2Axis:
    def __init__(self, pan_pin, tilt_pin, transition_type='instant', transition_speed=1.0):
        # Ensure pins are different to prevent conflicts
        if pan_pin == tilt_pin:
            raise ValueError("Pan and Tilt pins must be different.")

        GPIO.setmode(GPIO.BOARD)

        self.pan = servo.Servo(
            pin=pan_pin,
            min_duty=2.5,
            max_duty=12.5,
            min_angle=0.0,
            max_angle=180.0
            transition_type = self.transition_type
            transition_speed = self.transition_speed
        )

        self.tilt = servo.Servo(
            pin=tilt_pin,
            min_duty=2.5,
            max_duty=12.5,
            min_angle=0.0,
            max_angle=180.0
            transition_type = self.transition_type
            transition_speed = self.transition_speed
        )

    def set_pan(self, angle):
        # Clamp angle to limits to prevent hardware damage
        angle = max(0.0, min(180.0, angle))
        self.pan.set_angle(angle)

    def set_tilt(self, angle):
        # Clamp angle to limits
        angle = max(0.0, min(180.0, angle))
        self.tilt.set_angle(angle)

    def set_position(self, pan_angle, tilt_angle):
        # TO DO: Add threaded approach
        self.set_pan(pan_angle)
        self.set_tilt(tilt_angle)

    def center(self):
        self.set_position(90.0, 90.0)

    def shutdown(self):
        # Clean up the servo library objects first
        self.pan.cleanup()
        self.tilt.cleanup()
        
        # Clean up GPIO
        GPIO.cleanup()

