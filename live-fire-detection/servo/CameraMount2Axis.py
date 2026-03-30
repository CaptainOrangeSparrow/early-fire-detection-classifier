import threading
import time
import Jetson.GPIO as GPIO
from . import servo


class CameraMount2Axis:
    """
    Two-axis camera mount controller built on top of two Servo instances.

    Additions over the base version
    --------------------------------
    * start_scan()  — begins a raster (boustrophedon) scan pattern in a
                      background thread, covering the full pan × tilt range.
    * stop_scan()   — interrupts an active scan and holds current position.
    * is_scanning() — returns True while a scan is in progress.

    Raster scan pattern
    --------------------
    The tilt axis is divided into ``tilt_steps`` rows evenly spaced across
    [tilt_min, tilt_max].  For each row the pan axis sweeps across
    [pan_min, pan_max] in ``pan_steps`` stops, alternating direction each
    row (boustrophedon / "snake" pattern) to minimise travel time.

    The mount dwells at each waypoint long enough to distribute the total
    ``duration`` evenly across all (tilt_steps × pan_steps) positions.
    """

    def __init__(
        self,
        pan_pin,
        tilt_pin,
        transition_type='instant',
        transition_speed=1.0,
        pan_limits=None,
        tilt_limits=None,
        update_rate_hz=50.0
    ):
        if pan_pin == tilt_pin:
            raise ValueError("Pan and Tilt pins must be different.")

        GPIO.setmode(GPIO.BOARD)

        # Default limits
        pan_limits  = pan_limits  or (0.0,  180.0)
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
        self._target_pan  = self.pan.get_angle()
        self._target_tilt = self.tilt.get_angle()

        self._lock         = threading.Lock()
        self._update_event = threading.Event()

        self._running       = True
        self._update_period = 1.0 / update_rate_hz

        # Command dispatcher thread
        self._thread = threading.Thread(
            target=self._command_worker,
            daemon=True
        )
        self._thread.start()

        # ── Scan state ────────────────────────────────────────────────
        self._scan_thread  = None
        self._scan_running = False
        self._scan_lock    = threading.Lock()

    # ==========================================================================
    # Command Worker Thread
    # ==========================================================================

    def _command_worker(self):
        while self._running:
            self._update_event.wait(self._update_period)

            with self._lock:
                pan  = self._target_pan
                tilt = self._target_tilt
                self._update_event.clear()

            self.pan.set_angle(pan)
            self.tilt.set_angle(tilt)

    # ==========================================================================
    # Public API — Position Control
    # ==========================================================================

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
            self._target_pan  = pan_angle
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
        """Move both axes to their geometric midpoints."""
        pan_mid  = (self.pan.min_limit  + self.pan.max_limit)  / 2.0
        tilt_mid = (self.tilt.min_limit + self.tilt.max_limit) / 2.0
        self.set_position(pan_mid, tilt_mid)

    # ==========================================================================
    # Public API — Raster Scan
    # ==========================================================================

    def start_scan(self, pan_sweep_time: float = 20.0):

        with self._scan_lock:

            if self._scan_running:
                return

            self._scan_running = True

            self._scan_thread = threading.Thread(
                target=self._scan_worker,
                args=(pan_sweep_time,),
                daemon=True
            )

            self._scan_thread.start()

    def stop_scan(self):
        """
        Stop an active scan and hold the current position.
        Blocks until the scan thread exits (at most one dwell interval).
        """
        with self._scan_lock:
            self._scan_running = False

        if self._scan_thread is not None:
            self._scan_thread.join(timeout=5.0)
            self._scan_thread = None

    def is_scanning(self) -> bool:
        """Return True while a scan thread is active."""
        with self._scan_lock:
            return self._scan_running

    # ==========================================================================
    # Scan Worker (private)
    # ==========================================================================

    def _generate_waypoints(self, tilt_steps: int, pan_steps: int) -> list:
        """
        Pre-compute the ordered list of (pan, tilt) waypoints for one full
        raster sweep.

        Layout
        ------
        * Rows run along the tilt axis (top → bottom or configured range).
        * Columns run along the pan axis, alternating L→R / R→L each row
          (boustrophedon pattern) to minimise inter-row travel.

        Args:
            tilt_steps: Number of distinct tilt positions (rows).
            pan_steps:  Number of distinct pan positions per row (columns).

        Returns:
            List of (pan_angle, tilt_angle) tuples.
        """
        pan_min  = self.pan.min_limit
        pan_max  = self.pan.max_limit
        tilt_min = self.tilt.min_limit
        tilt_max = self.tilt.max_limit

        # Evenly space positions across each axis
        if tilt_steps > 1:
            tilt_positions = [
                tilt_min + i * (tilt_max - tilt_min) / (tilt_steps - 1)
                for i in range(tilt_steps)
            ]
        else:
            tilt_positions = [(tilt_min + tilt_max) / 2.0]

        if pan_steps > 1:
            pan_positions = [
                pan_min + i * (pan_max - pan_min) / (pan_steps - 1)
                for i in range(pan_steps)
            ]
        else:
            pan_positions = [(pan_min + pan_max) / 2.0]

        waypoints = []
        for row_idx, tilt in enumerate(tilt_positions):
            # Alternate pan direction each row (boustrophedon)
            row_pans = pan_positions if row_idx % 2 == 0 else list(reversed(pan_positions))
            for pan in row_pans:
                waypoints.append((pan, tilt))

        return waypoints

    def _scan_worker(self, pan_sweep_time: float):

        pan_min  = self.pan.min_limit
        pan_max  = self.pan.max_limit
        tilt_min = self.tilt.min_limit
        tilt_max = self.tilt.max_limit

        # camera parameters
        vertical_fov = 42.0
        overlap = 0.30

        tilt_step = vertical_fov * (1.0 - overlap)

        # generate tilt rows
        tilt_positions = []
        t = tilt_min
        while t <= tilt_max:
            tilt_positions.append(t)
            t += tilt_step

        pause_time = 0.3

        print(f"[SCAN] Smooth row scan: {len(tilt_positions)} rows")

        while True:

            with self._scan_lock:
                if not self._scan_running:
                    return

            # snap to start corner
            self.set_position(pan_min, tilt_positions[0])
            time.sleep(1.0)

            direction = 1

            for tilt in tilt_positions:

                with self._scan_lock:
                    if not self._scan_running:
                        return

                # move tilt
                self.set_tilt(tilt)

                time.sleep(0.5)

                if direction > 0:
                    target_pan = pan_max
                else:
                    target_pan = pan_min

                # sweep pan
                self.set_pan(target_pan)

                start = time.time()

                while (time.time() - start) < pan_sweep_time:

                    with self._scan_lock:
                        if not self._scan_running:
                            return

                    time.sleep(0.05)

                time.sleep(pause_time)

                direction *= -1

    # ==========================================================================
    # Shutdown & Safety
    # ==========================================================================

    def shutdown(self, center: bool = False):
        """
        Full shutdown.  Stops scan, optionally centres, then cleans up GPIO.

        Args:
            center: If True, moves to the geometric centre before shutting down.
        """
        self.stop_scan()

        if center:
            self.center()
            time.sleep(0.5)

        self._running = True  # keep command worker alive long enough to apply centre
        self._update_event.set()
        time.sleep(0.1)

        self._running = False
        self._update_event.set()
        self._thread.join(timeout=1.0)

        self.pan.cleanup()
        self.tilt.cleanup()