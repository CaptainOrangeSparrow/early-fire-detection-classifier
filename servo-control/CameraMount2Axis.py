import servo
import Jetson.GPIO as GPIO

class CameraMount2Axis:
    def __init__(self, pan_pin, tilt_pin, transition_type='instant', transition_speed=1.0, 
                 pan_limits=None, tilt_limits=None):
        # Ensure pins are different to prevent conflicts
        if pan_pin == tilt_pin:
            raise ValueError("Pan and Tilt pins must be different.")

        GPIO.setmode(GPIO.BOARD)
        
        # To view transition types -> servo.py
        self.transition_type = transition_type
        self.transition_speed = transition_speed

        # Handle default limits (0-180 if not provided)
        if pan_limits is None:
            pan_limits = (0.0, 180.0)
        if tilt_limits is None:
            tilt_limits = (0.0, 180.0)

        self.pan = servo.Servo(
            pin=pan_pin,
            min_angle=0.0,
            max_angle=180.0,
            transition_type=self.transition_type,
            transition_speed=self.transition_speed,
            min_limit=pan_limits[0],
            max_limit=pan_limits[1]
        )

        self.tilt = servo.Servo(
            pin=tilt_pin,
            min_angle=0.0,
            max_angle=180.0,
            transition_type=self.transition_type,
            transition_speed=self.transition_speed,
            min_limit=tilt_limits[0],
            max_limit=tilt_limits[1]
        )

    def set_pan(self, angle):
        # Clamping is now handled inside the Servo class using limits
        self.pan.set_angle(angle)

    def set_tilt(self, angle):
        # Clamping is now handled inside the Servo class using limits
        self.tilt.set_angle(angle)

    def set_position(self, pan_angle, tilt_angle):
        # TO DO: Add threaded approach
        self.set_pan(pan_angle)
        self.set_tilt(tilt_angle)
        
    def set_limits(self, pan_limits=None, tilt_limits=None):
        """Update software limits for the servos."""
        if pan_limits:
            self.pan.set_limits(pan_limits[0], pan_limits[1])
        if tilt_limits:
            self.tilt.set_limits(tilt_limits[0], tilt_limits[1])

    def center(self):
        # Center will now center within the allowed limits if initialized there,
        # but strict "center" of 90 is usually safe.
        # To be perfectly safe, we could calculate midpoint of limits, 
        # but 90 is standard.
        self.set_position(90.0, 90.0)

    def shutdown(self):
        # Clean up the servo library objects first
        self.pan.cleanup()
        self.tilt.cleanup()
        
        # Clean up GPIO
        GPIO.cleanup()
