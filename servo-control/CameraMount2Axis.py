import threading
import time
import Jetson.GPIO as GPIO
import servo


class CameraMount2Axis:
    def __init__(
        self,
        pan_pin,
        tilt_pin,
        transition_type='instant',
        transition_speed=1.0,
        pan_limits=None,
        tilt_limits=None,
        update_rate_hz=100.0
    ):
        if pan_pin == tilt_pin:
            raise ValueError("Pan and Tilt pins must be different.")

        GPIO.setmode(GPIO.BOARD)

        # Default limits
        pan_limits = pan_limits or (0.0, 180.0)
        tilt_limits = tilt_limits or (90.0, 180.0)

        # Servo instances (each has its own worker thread)
        self.pan = servo.Servo(
            pin=pan_pin,
            transition_type=transition_type,
            transition_speed=transition_speed,
            min_limit=pan_limits[0],
            max_limit=pan_limits[1]
        )

        self.tilt = servo.Servo(
            pin=tilt_pin,
            transition_type=transition_type,
            transition_speed=transition_speed,
            min_limit=tilt_limits[0],
            max_limit=tilt_limits[1]
        )

        # Shared target state
        self._target_pan = self.pan.get_angle()
        self._target_tilt = self.tilt.get_angle()

        self._lock = threading.Lock()
        self._update_event = threading.Event()

        self._running = True
        self._update_period = 1.0 / update_rate_hz

        # Command dispatcher thread
        self._thread = threading.Thread(
            target=self._command_worker,
            daemon=True
        )
        self._thread.start()

    # =========================
    # Command Worker Thread
    # =========================
    def _command_worker(self):
        while self._running:
            # Wait until there's a change or timeout
            self._update_event.wait(self._update_period)

            with self._lock:
                pan = self._target_pan
                tilt = self._target_tilt
                self._update_event.clear()

            # Apply synchronously
            self.pan.set_angle(pan)
            self.tilt.set_angle(tilt)

    # =========================
    # Public API
    # =========================
    def set_pan(self, angle):
        with self._lock:
            self._target_pan = angle
            self._update_event.set()

    def set_tilt(self, angle):
        with self._lock:
            self._target_tilt = angle
            self._update_event.set()

    def set_position(self, pan_angle, tilt_angle):
        with self._lock:
            self._target_pan = pan_angle
            self._target_tilt = tilt_angle
            self._update_event.set()

    def get_pan(self):
        return self.pan.get_angle()

    def get_tilt(self):
        return self.tilt.get_angle()

    def set_limits(self, pan_limits=None, tilt_limits=None):
        if pan_limits:
            self.pan.set_limits(*pan_limits)
        if tilt_limits:
            self.tilt.set_limits(*tilt_limits)

    def center(self):
        self.set_position(90.0, 90.0)

    # =========================
    # Shutdown & Safety
    # =========================
    def shutdown(self, center=False):
        """
        Immediate shutdown.
        Optionally center first.
        """
        if center:
            self.set_position(90.0, 90.0)
            time.sleep(0.25)

        self._running = False
        self._update_event.set()
        self._thread.join(timeout=1.0)

        self.pan.cleanup()
        self.tilt.cleanup()
        GPIO.cleanup()