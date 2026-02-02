import servo

class CameraMount2Axis:
    def __init__(self, pan_pin, tilt_pin):
        GPIO.setmode(GPIO.BOARD)

        self.pan = Servo(
            pin=pan_pin,
            min_duty=2.5,
            max_duty=12.5,
            min_angle=0.0,
            max_angle=180.0
        )

        self.tilt = Servo(
            pin=tilt_pin,
            min_duty=2.5,
            max_duty=12.5,
            min_angle=0.0,
            max_angle=180.0
        )

    def set_pan(self, angle):
        self.pan.set_angle(angle)

    def set_tilt(self, angle):
        self.tilt.set_angle(angle)

    def set_position(self, pan_angle, tilt_angle):
        self.set_pan(pan_angle)
        self.set_tilt(tilt_angle)

    def center(self):
        self.set_position(90.0, 90.0)

    def shutdown(self):
        self.pan.cleanup()
        self.tilt.cleanup()
        GPIO.cleanup()
