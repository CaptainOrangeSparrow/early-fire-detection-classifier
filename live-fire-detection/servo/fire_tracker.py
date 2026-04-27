"""
Refactored pan-tilt fire tracking module.

Classes (in dependency order):
    PID:            Discrete difference-equation PID controller.
    ObjCenter:      Extracts fire centroid from fused-detection results.
    TrackerState:   FSM states (SCANNING, TRACKING, HOLDING, LOST).
    FireTracker:    Accepts ml_results object each tick, state machine, PID, mount control, and callbacks are all handled internally.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from typing import Callable, Optional
import csv
import time
from datetime import datetime
import random

from .CameraMount2Axis import CameraMount2Axis

# PID ─────────────────────────────────────────────────────────────────────────────
class PID:
    """
    Discrete PID controller using the Z-transform difference equation:

        Δu[n] = k1·e[n] + k2·e[n-1] + k3·e[n-2]
        u[n]  = u[n-1] + Δu[n]

    Coefficients:
        k1 =  kP + kI + kD
        k2 = -kP - 2·kD
        k3 =  kD

    Output is clamped to [min_output, max_output].
    """

    def __init__(
        self,
        kP:         float = 1.0,
        kI:         float = 0.0,
        kD:         float = 0.0,
        min_output: float = -180.0,
        max_output: float =  180.0,
    ) -> None:
        self.kP = kP
        self.kI = kI
        self.kD = kD
        self.min_output = min_output
        self.max_output = max_output

        # Pre-computed difference-equation coefficients
        self._k1 =  kP + kI + kD
        self._k2 = -kP - 2.0 * kD
        self._k3 =  kD

        # Internal state — reset via initialize()
        self._prev_errors: deque[float] = deque([0.0, 0.0], maxlen=2)
        self._prev_output: float = 0.0

    def initialize(self) -> None:
        """
        Must be called before beginning each new tracking phase to prevent
        integral and derivative windup from previous phases.
        """
        self._prev_errors = deque([0.0, 0.0], maxlen=2)
        self._prev_output = 0.0

    def update(self, error: float, px_error: float) -> float:
        """
        Compute the control output for the given angular error.
        
        error: angular tracking error in degrees.
        """

        if abs(px_error) < 8:  # Deadband threshold in pixels to prevent jitter when the target is close enough to center
            return 0.0

        delta = (
            self._k1 * error
            + self._k2 * self._prev_errors[0]
            + self._k3 * self._prev_errors[1]
        )
        self._prev_errors.appendleft(error)
        output = max(self.min_output, min(self.max_output, self._prev_output + delta))
        self._prev_output = output
        
        # Return angular delta to current position
        return output


# ObjCenter ─────────────────────────────────────────────────────────────────────────────
class ObjCenter:
    """
    Extracts the centroid of the fire bounding box from a
    process_fused_detection() result dict.

    Filters out detections that are too small (likely false positives) or too large (fire already filling the frame).

    Returns the frame camera center when no fire detection
    """

    def __init__(self, frame_w: int, frame_h: int) -> None:
        self._frame_w    = frame_w
        self._frame_h    = frame_h
        self._frame_area = frame_w * frame_h
        self._cx         = frame_w  // 2
        self._cy         = frame_h  // 2

    @property
    def center(self) -> tuple[int, int]:
        # Frame centre pixel coordinates
        return self._cx, self._cy

    def update(
        self,
        results:      dict,
        coverage_min: float = 0.0,
        coverage_max: float = 0.2,
    ) -> tuple[tuple[int, int], tuple[int, int], bool]:
        """
        Parse a results dict from process_fused_detection().

        Returns:
            ((obj_x, obj_y), (cx, cy), fire_detected)

            obj_x/obj_y is the bounding-box centroid when a valid detection
            exists; falls back to (cx, cy) when it does not.
        """
        # Validate coverage thresholds
        assert 0.0 <  coverage_max <= 1.0, "coverage_max must be in (0, 1]"
        assert 0.0 <= coverage_min <= 1.0, "coverage_min must be in [0, 1]"
        assert coverage_max >= coverage_min, "coverage_max must be ≥ coverage_min"

        meta = results.get("meta_decision", {})
        fire_detected = meta.get("fire_detection_boolean", False)
        box = meta.get("box", None)

        if fire_detected and box is not None and len(box) == 4:
            # Extract bounding box and compute area coverage
            x1, y1, x2, y2 = box
            area_box = (x2 - x1) * (y2 - y1)
            
            # Boolean flag for whether the bounding box area is within the specified coverage thresholds
            in_range = (coverage_min * self._frame_area <= area_box <= coverage_max * self._frame_area)
            
            # Compute centroid of the bounding box
            if in_range:
                return (
                    (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                    (self._cx, self._cy),
                    True,
                )

        return (self._cx, self._cy), (self._cx, self._cy), False


# FSM state ─────────────────────────────────────────────────────────────────────────────
class TrackerState(Enum):
    SCANNING = auto() # Performing raster sweep looking for fire
    TRACKING = auto() # PID control to keep fire centroid centered
    HOLDING  = auto() # Brief hold after losing ml detection to prevent jitter
    LOST     = auto() # Restart scan after confirmed loss 

# FireTracker ─────────────────────────────────────────────────────────────────────────────

class FireTracker:
    """
    Pan-Tilt fire tracking controller.

    Integrates PID, ObjCenter, and CameraMount2Axis into a single interface
    driven by an explicit FSM.  Each control-loop tick, call update(ml_results)
    and the class handles:

    Centroid extraction from the fused-detection result dict
    FSM transitions  (SCANNING, TRACKING, HOLDING, LOST, back to SCANNING)
    Automatic speed switching (scan_speed vs track_speed)
    PID computation and mount positioning
    Detection Jitter prevention hold with a threading.Timer
    Scan resume delay with a second threading.Timer
    Callback for acquired / lost / per-tick-tracking events (debugging, telemetry, audio, etc)

    Callbacks:
    on_fire_acquired  Callable[[], None]
        Fired once on SCANNING → TRACKING.
        Runs in a ThreadPoolExecutor worker (non-blocking to the tick thread).

    on_fire_lost  Callable[[], None]
        Fired once on HOLDING → LOST.
        Runs in a ThreadPoolExecutor worker (non-blocking to the tick thread).

    on_fire_tracking  Callable[[float, float, float, float], None]
        Called synchronously every tick while in TRACKING state.
        Signature: (error_pan_deg, error_tilt_deg, new_pan_deg, new_tilt_deg)
        Keep this callback lightweight — it runs on the tick thread.

    Parameters:
    pan_pin, tilt_pin       GPIO pins for the servos.
    pan_limits, tilt_limits (min_deg, max_deg) hard travel limits.
    frame_w, frame_h        Camera resolution in pixels.
    hfov_deg, vfov_deg      Full Camera FOV in degrees.
    pan_kp/ki/kd            PID gains for the pan axis.
    tilt_kp/ki/kd           PID gains for the tilt axis.
    scan_speed              Servo speed during SCANNING.
    track_speed             Servo speed during TRACKING.
    pan_sweep_time          Seconds per full pan sweep in scan mode.
    track_loss_timeout      Seconds to hold position after losing detection
    scan_resume_delay       Seconds to wait after confirmed loss before restarting the sweep.
    fire_coverage_min/max   Fraction of frame area [0, 1] bounding box must occupy to be treated as a valid target.
    pan_error_sign          ±1 applied to the pan angular error. Controls direction of servo correction.
    tilt_error_sign         ±1 applied to the tilt angular error. Controls direction of servo correction.
    on_fire_acquired        Callbacks using fd_main_v2 functions to play audio alerts.
    on_fire_lost            Callbacks used to debug when a fire is lost.
    on_fire_tracking        Callbacks used to provide tracking feedback.
    debug                   Print per-tick telemetry and state-change banners.
    """

    # ── Default constants (mirrors pan_tilt_tracking.py originals) ────────────
    _D_PAN_KP,  _D_PAN_KI,  _D_PAN_KD  = 0.20,  0.020, 0.020
    _D_TILT_KP, _D_TILT_KI, _D_TILT_KD = 0.15,  0.015, 0.015
    _D_PAN_LIMITS  = (0.0, 180.0)
    _D_TILT_LIMITS = (0.0, 135.0)
    _D_HFOV_DEG    = 56.0
    _D_VFOV_DEG    = 42.0
    _D_FRAME_W     = 640
    _D_FRAME_H     = 480

    def __init__(
        self,
        *,
        # Mount hardware
        pan_pin:  int,
        tilt_pin: int,
        pan_limits:  tuple[float, float] = _D_PAN_LIMITS,
        tilt_limits: tuple[float, float] = _D_TILT_LIMITS,
        
        # Camera
        frame_w:  int   = _D_FRAME_W,
        frame_h:  int   = _D_FRAME_H,
        hfov_deg: float = _D_HFOV_DEG,
        vfov_deg: float = _D_VFOV_DEG,
        
        # PID gains
        pan_kp:  float = _D_PAN_KP,
        pan_ki:  float = _D_PAN_KI,
        pan_kd:  float = _D_PAN_KD,
        tilt_kp: float = _D_TILT_KP,
        tilt_ki: float = _D_TILT_KI,
        tilt_kd: float = _D_TILT_KD,
        
        # Speeds
        scan_speed:     float = 1.5,
        track_speed:    float = 3.0,
        pan_sweep_time: float = 4.0,
        
        # Timing
        track_loss_timeout: float = 0.5,
        scan_resume_delay:  float = 3.0,
        
        # Coverage thresholds
        fire_coverage_min: float = 0.0,
        fire_coverage_max: float = 0.2,
        
        # Axis sign conventions
        pan_error_sign:  int = -1,
        tilt_error_sign: int = +1,

        # Callbacks
        on_fire_acquired: Optional[Callable[[], None]]                            = None,
        on_fire_lost:     Optional[Callable[[], None]]                            = None,
        on_fire_tracking: Optional[Callable[[float, float, float, float], None]]  = None,
        

        
        # Debug
        debug: bool = False,
        
        sysid_mode: bool = False,
        sysid_duration_s: float = 90.0,
        sysid_freq_hz: float = 3.0 
    ) -> None:

        # ── Mount ─────────────────────────────────────────────────────────
        self._mount = CameraMount2Axis(
            pan_pin=pan_pin,
            tilt_pin=tilt_pin,
            transition_type="s-curve",
            transition_speed=track_speed,
            pan_limits=pan_limits,
            tilt_limits=tilt_limits,
            update_rate_hz=50.0,    # Attempt to increase to 100, 200, 300 Hz and verify stability of the PID loop at each step
        )
        self._scan_speed     = scan_speed
        self._track_speed    = track_speed
        self._pan_sweep_time = pan_sweep_time

        # ── PIDs ──────────────────────────────────────────────────────────
        self._pid_pan = PID(
            kP=pan_kp, kI=pan_ki, kD=pan_kd,
            min_output=-hfov_deg, max_output=hfov_deg,
        )
        self._pid_tilt = PID(
            kP=tilt_kp, kI=tilt_ki, kD=tilt_kd,
            min_output=-vfov_deg, max_output=vfov_deg,
        )
        self._pid_pan.initialize()
        self._pid_tilt.initialize()

        # ── ObjCenter ─────────────────────────────────────────────────────
        self._obj_center = ObjCenter(frame_w=frame_w, frame_h=frame_h)

        # ── Camera geometry ───────────────────────────────────────────────
        self._half_hfov_rad   = math.radians(hfov_deg / 2.0)
        self._half_vfov_rad   = math.radians(vfov_deg / 2.0)
        self._frame_w         = frame_w
        self._frame_h         = frame_h
        self._pan_error_sign  = pan_error_sign
        self._tilt_error_sign = tilt_error_sign

        # ── Coverage thresholds ───────────────────────────────────────────
        self._coverage_min = fire_coverage_min
        self._coverage_max = fire_coverage_max

        # ── Timing ────────────────────────────────────────────────────────
        self._track_loss_timeout = track_loss_timeout
        self._scan_resume_delay  = scan_resume_delay

        # ── Callbacks ─────────────────────────────────────────────────────
        # on_fire_acquired and on_fire_lost run in a dedicated executor so that
        # I/O-heavy work (audio, telemetry) never blocks the tick thread.
        # on_fire_tracking is called synchronously each tick — keep it light.
        self._on_fire_acquired_cb = on_fire_acquired
        self._on_fire_lost_cb     = on_fire_lost
        self._on_fire_tracking_cb = on_fire_tracking
        self._cb_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="tracker_cb",
        )

        # PID
        
        # Graphing PID Errors for debugging and tuning purposes.  Writes to a new CSV file each time the tracker enters TRACKING state from SCANNING state.  Columns: [dy_px, dx_px, timestamp]
        now = datetime.now()
        self.filelocation = f"/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/servo/pid_recording_sessions/pid_session_{now:%Y-%m-%d_%H-%M-%S}.csv"

        # ── FSM ───────────────────────────────────────────────────────────
        self._state      = TrackerState.SCANNING
        self._state_lock = threading.Lock()
        
        # These timers drive transitions off the tick thread.
        # Always cancel before restarting.
        self._loss_timer:   Optional[threading.Timer] = None
        self._resume_timer: Optional[threading.Timer] = None

        # ── Debug ─────────────────────────────────────────────────────────
        self._debug = debug
        
        # ── Axis limits (stored for sysid amplitude clamping) ────────────
        self._pan_limits  = pan_limits
        self._tilt_limits = tilt_limits

        # ── Sysid mode ────────────────────────────────────────────────────
        self._sysid_mode     = sysid_mode
        self._sysid_duration_s = sysid_duration_s
        self._sysid_freq_hz  = sysid_freq_hz
        self._sysid_active   = False
        self._sysid_done     = False
        self._sysid_seq_pan: list[float]  = []
        self._sysid_seq_tilt: list[float] = []
        self._sysid_index    = 0
        self._sysid_base_pan  = 0.0
        self._sysid_base_tilt = 0.0
        self._sysid_start_t   = 0.0
        self._sysid_last_switch_t = 0.0
        if sysid_mode:
            self._mount.set_position(90.0, 90.0)  # Start centered
            now = datetime.now()
            self._sysid_filepath = (
                f"/home/firedistinguisher/projects/early-fire-detection-classifier/"
                f"live-fire-detection/servo/sysid_sessions/"
                f"sysid_{now:%Y-%m-%d_%H-%M-%S}.csv"
            ) 

        # ── Start scanning immediately ────────────────────────────────────
        if not sysid_mode:
            self._mount.set_speeds(speed=scan_speed)
            self._mount.start_scan(pan_sweep_time=pan_sweep_time, speed=scan_speed)

    # Public API ─────────────────────────────────────────────────────────────────────────
    def update(self, ml_results: dict) -> TrackerState:
        """
        Main tick entry point.  
        
        Extracts the fire centroid from ml_results, advances the FSM, and
        drives the mount via PID when in TRACKING state.

        Returns the TrackerState after processing this tick.
        """
        (obj_x, obj_y), (cx, cy), fire_detected = self._obj_center.update(
            ml_results,
            coverage_min=self._coverage_min,
            coverage_max=self._coverage_max,
        )

        if self._sysid_mode:
            if fire_detected and not self._sysid_done:
                self._handle_sysid_tick(obj_x, obj_y, cx, cy)
            elif not fire_detected:
                self._log("[sysid] No fire detected – sysid inactive.")
            return self.get_state()  # Return early in sysid mode since we don't want to run the normal FSM logic

        if fire_detected:
            self._handle_detection(obj_x, obj_y, cx, cy, ml_results)
        else:
            self._handle_no_detection()

        # Return the current state for telemetry/debugging purposes
        return self.get_state()

    def get_state(self) -> TrackerState:
        # Return current FSM state
        with self._state_lock:
            return self._state

    def get_mount(self) -> CameraMount2Axis:
        """
        Direct access to the underlying CameraMount2Axis.
        Use this only when you need internal mount functionality not exposed.
        """
        return self._mount

    def get_pid_pan(self) -> PID:
        # Access the pan PID controller to retune gains at runtime
        return self._pid_pan

    def get_pid_tilt(self) -> PID:
        # Access the tilt PID controller to retune gains at runtime)
        return self._pid_tilt

    def start_scan(
        self,
        pan_sweep_time: Optional[float] = None,
        speed:          Optional[float] = None,
    ) -> None:
        """
        Manually start or restart a scan sweep.  Cancels any running timers and
        forces the FSM into SCANNING regardless of current state.

        Useful for external triggers (e.g., periodic forced re-sweep, test
        harness, or manual override from the UI).
        """
        with self._state_lock:
            self._cancel_timers()
            self._state = TrackerState.SCANNING
        sp = speed if speed is not None else self._scan_speed
        pt = pan_sweep_time if pan_sweep_time is not None else self._pan_sweep_time
        self._mount.set_speeds(speed=sp)
        self._mount.start_scan(pan_sweep_time=pt, speed=sp)

    def stop_scan(self) -> None:
        # Stop the scan sweep without changing tracker state
        self._mount.stop_scan()

    def shutdown(self, center: bool = True) -> None:
        """
        Shutdown.  Cancels state-transition timers, shuts down the
        callback executor, and halts mount.
        """
        with self._state_lock:
            self._cancel_timers()
        self._cb_executor.shutdown(wait=False)
        self._mount.stop_scan()
        self._mount.shutdown(center=center)

    @staticmethod
    def _write_control_graph(filename, dy_ang, dx_ang, cmd_pan_ang, cmd_tilt_ang) -> None: 
        with open(filename, 'a') as outfile:
            writer = csv.writer(outfile)
            writer.writerow([dy_ang,  dx_ang, cmd_pan_ang, cmd_tilt_ang, time.perf_counter()])

    # FSM handlers  (called from tick thread or timer threads) ─────────────────────────────────────────────────────────────────────────
    def _handle_detection(
        self,
        obj_x: int,
        obj_y: int,
        cx:    int,
        cy:    int,
        ml_results: dict,
    ) -> None:
        # Process a tick where a valid fire centroid was detected
        print("**********************************************\n**********************************************\n**********************************************")
        # State Entry Handling
        with self._state_lock:
            prev = self._state

            if prev == TrackerState.SCANNING:
                # SCANNING to TRACKING
                # Stop scan, switch to track speed, reset PID
                self._cancel_timers()
                self._mount.stop_scan()
                self._mount.set_speeds(speed=self._track_speed)
                self._pid_pan.initialize()
                self._pid_tilt.initialize()
                self._state = TrackerState.TRACKING
                if self._on_fire_acquired_cb:
                    self._cb_executor.submit(self._on_fire_acquired_cb)
                self._log_banner("*", "Fire detected – stopping scan, entering tracking.")

                # Prepare File location for store of PID pixel errors (Called Once on transition to tracking state from scanning state)
                if self._debug:
                    now = datetime.now()
                    self.filelocation = f"/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/servo/pid_recording_sessions/pid_session_{now:%Y-%m-%d_%H-%M-%S}.csv"


            elif prev in (TrackerState.HOLDING, TrackerState.LOST):
                #  Re-acquisition from HOLDING or LOST states:
                # Cancel the hold or resume timer and return to TRACKING.
                # If the resume timer already fired and the mount is scanning,
                # stop it and re-enter track mode cleanly.
                self._cancel_timers()
                if self._mount.is_scanning():
                    self._mount.stop_scan()
                    self._mount.set_speeds(speed=self._track_speed)
                    self._pid_pan.initialize()
                    self._pid_tilt.initialize()
                self._state = TrackerState.TRACKING
                self._log("[tracker] Fire reacquired – continuing tracking.")
                

        # PID loop outside lock since it doesn't modify shared state
        dx_px = obj_x - cx
        dy_px = obj_y - cy


        
        angle_pan = self._pixel_to_angle(dx_px, self._half_hfov_rad, self._frame_w)
        angle_tilt = self._pixel_to_angle(dy_px, self._half_vfov_rad, self._frame_h)


        error_pan  = self._pan_error_sign  * angle_pan
        error_tilt = self._tilt_error_sign * angle_tilt

        pan_update  = self._pid_pan.update(error_pan, dx_px)
        tilt_update = self._pid_tilt.update(error_tilt, dy_px)
        
        

        new_pan  = self._mount.get_pan()  + pan_update
        new_tilt = self._mount.get_tilt() + tilt_update

        
        # Write to preexisting csv or create csv to hold pixel errors
        if self._debug: 
            self._write_control_graph(filename=self.filelocation, dx_ang=angle_pan, dy_ang=angle_tilt, cmd_pan_ang=new_pan, cmd_tilt_ang=new_tilt)

        self._mount.set_position(new_pan, new_tilt)

        if self._debug:
            conf = ml_results.get("meta_decision", {}).get("confidence", 0.0)
            print(
                f"[tracker] TRACKING | "
                f"obj=({obj_x},{obj_y}) conf={conf:.2f} | "
                f"err=({error_pan:+.2f}°, {error_tilt:+.2f}°) | "
                f"px_err=({dx_px:+.1f}px, {dy_px:+.1f}px) | "
                f"pid=({pan_update:+.2f}°, {tilt_update:+.2f}°) | "
                f"mount=({new_pan:.1f}°, {new_tilt:.1f}°)"
            )

        # on_fire_tracking callback to allow fd_main_v3 to produce feedback (audio, telemetry, etc) 
        # (optional - Not used in fd_main_v3 but available for future use or external triggers)  
        if self._on_fire_tracking_cb:
            self._on_fire_tracking_cb(error_pan, error_tilt, new_pan, new_tilt)

    def _handle_no_detection(self) -> None:
        # Process a tick where no valid fire centroid was detected
        with self._state_lock:
            if self._state != TrackerState.TRACKING:
                return

            #  TRACKING to HOLDING
            # Start the timeout timer.  The mount holds its current
            # position silently; no PID update is applied this tick.
            self._cancel_timers()
            
            # Update state befthe timer
            self._state = TrackerState.HOLDING
            
            # Start the hold timer to handle detection losses.  
            # If this timer expires without reacquisition, the tracker transitions to LOST and starts the resume timer.
            self._loss_timer = threading.Timer(
                self._track_loss_timeout, self._on_hold_expired
            )
            self._loss_timer.daemon = True
            self._loss_timer.start()

        self._log(
            f"[tracker] HOLDING | No detection – holding for "
            f"{self._track_loss_timeout:.2f}s before declaring loss."
        )

    # Timer callbacks  (run in the threading module's internal thread pool)     # ─────────────────────────────────────────────────────────────────────────
    def _on_hold_expired(self) -> None:
        """
        Fires after track_loss_timeout with no reacquisition.
        HOLDING to LOST, starts the scan-resume countdown.
        """
        with self._state_lock:
            if self._state != TrackerState.HOLDING:
                return  # State reacquired while the hold timer was running.
            self._state = TrackerState.LOST
            self._resume_timer = threading.Timer(
                self._scan_resume_delay, self._on_resume_expired
            )
            self._resume_timer.daemon = True
            self._resume_timer.start()

        self._log_banner("~", f"Fire lost – resuming scan in {self._scan_resume_delay:.1f}s.")
        if self._on_fire_lost_cb:
            self._cb_executor.submit(self._on_fire_lost_cb)

    def _on_resume_expired(self) -> None:
        """
        Fires after scan_resume_delay with no reacquisition.
        LOST to SCANNING, restarts the boustrophedon sweep.
        """
        with self._state_lock:
            if self._state != TrackerState.LOST:
                return  # Reacquired while the resume timer was running.
            self._state = TrackerState.SCANNING

        # Reset PID state before the next possible track phase.
        self._pid_pan.initialize()
        self._pid_tilt.initialize()
        self._mount.set_speeds(speed=self._scan_speed)
        self._mount.start_scan(
            pan_sweep_time=self._pan_sweep_time,
            speed=self._scan_speed,
        )
        self._log("[tracker] SCANNING | No fire – scan resumed.")

    # Helpers ─────────────────────────────────────────────────────────────────────────
    def _cancel_timers(self) -> None:
        """
        Cancel both state-transition timers.
        MUST be called with self._state_lock held to avoid a race where
        a timer callback checks the state between cancel() and the caller's
        subsequent state write.
        """
        if self._loss_timer is not None:
            self._loss_timer.cancel()
            self._loss_timer = None
        if self._resume_timer is not None:
            self._resume_timer.cancel()
            self._resume_timer = None

    @staticmethod
    def _pixel_to_angle(
        pixel_offset: float,
        half_fov_rad: float,
        frame_dim:    int,
    ) -> float:
        """
        Convert a signed pixel offset from the frame centre to an angular
        displacement using the exact right-triangle derivation:

            φ = atan( 2x · tan(θ) / b )

        pixel_offset : Signed pixel distance from frame centre.
        half_fov_rad : Half-FOV for the axis in radians.
        frame_dim    : Total frame dimension in pixels for the axis.
        Returns      : Angular displacement φ in degrees.
        """
        return math.degrees(
            math.atan2(
                2.0 * pixel_offset * math.tan(half_fov_rad),
                frame_dim,
            )
        )
        
    @staticmethod
    def _angle_to_pixel(
        angle_deg:    float,
        half_fov_rad: float,
        frame_dim:    int,
    ) -> float:
        """
        Convert an angular displacement to a signed pixel offset from the
        frame centre — the exact inverse of _pixel_to_angle:
            x = b · tan(φ) / ( 2 · tan(θ) )
        angle_deg    : Angular displacement φ in degrees.
        half_fov_rad : Half-FOV for the axis in radians.
        frame_dim    : Total frame dimension in pixels for the axis.
        Returns      : Signed pixel distance from frame centre.
        """
        return (
            frame_dim * math.tan(math.radians(angle_deg))
            / (2.0 * math.tan(half_fov_rad))
        )
        
        
    @staticmethod
    def _generate_prbs(n: int, amplitude: float, seed: int = 42) -> list[float]:
        """
        Generate a pseudo-random binary sequence of length n with values
        ±amplitude.  Used to excite plant dynamics for system identification.

        n         : Number of steps.
        amplitude : Magnitude of each step in degrees.
        seed      : RNG seed for reproducibility.
        """
        rng = random.Random(seed)
        return [amplitude if rng.random() > 0.5 else -amplitude for _ in range(n)]
        
    def _handle_sysid_tick(self, obj_x: int, obj_y: int, cx: int, cy: int) -> None:
            """
            Open-loop PRBS tick for system identification.

            On first call: computes safe PRBS amplitude from the iron's current
            angular offset and FOV bounds, generates sequences, and saves base position.
            Each subsequent call: advances the PRBS index at sysid_freq_hz, commands
            the mount, and logs [dx_ang, dy_ang, cmd_pan, cmd_tilt, t].
            """
            t_now  = time.perf_counter()
            dx_px  = obj_x - cx
            dy_px  = obj_y - cy
            angle_pan  = self._pixel_to_angle(dx_px, self._half_hfov_rad, self._frame_w)
            angle_tilt = self._pixel_to_angle(dy_px, self._half_vfov_rad, self._frame_h)

            # ── First detection: initialize PRBS ──────────────────────────────
            if not self._sysid_active:
                self._sysid_base_pan  = self._mount.get_pan()
                self._sysid_base_tilt = self._mount.get_tilt()

                hfov_half = math.degrees(self._half_hfov_rad)   # half-FOV in deg
                vfov_half = math.degrees(self._half_vfov_rad)

                # Max perturbation that keeps iron in frame (image formula)
                margin    = 0.2
                amp_pan   = (hfov_half - abs(angle_pan))  * margin
                amp_tilt  = (vfov_half - abs(angle_tilt)) * margin

                # Also clamp so base ± amplitude stays within servo travel limits
                p_min, p_max = self._pan_limits
                t_min, t_max = self._tilt_limits
                amp_pan  = max(1.0, min(amp_pan,
                                        self._sysid_base_pan  - p_min,
                                        p_max - self._sysid_base_pan))
                amp_tilt = max(1.0, min(amp_tilt,
                                        self._sysid_base_tilt - t_min,
                                        t_max - self._sysid_base_tilt))

                n_steps = int(self._sysid_duration_s * self._sysid_freq_hz)
                # Different seeds so pan/tilt sequences are decorrelated
                self._sysid_seq_pan  = self._generate_prbs(n_steps, amp_pan,  seed=42)
                self._sysid_seq_tilt = self._generate_prbs(n_steps, amp_tilt, seed=137)
                self._sysid_index         = 0
                self._sysid_start_t       = t_now
                self._sysid_last_switch_t = t_now
                self._sysid_active        = True

                print(
                    f"[sysid] Initialized | "
                    f"base=({self._sysid_base_pan:.1f}°, {self._sysid_base_tilt:.1f}°) | "
                    f"amp=({amp_pan:.2f}°, {amp_tilt:.2f}°) | "
                    f"steps={n_steps} | duration={self._sysid_duration_s:.0f}s"
                )

            # ── Check if collection is complete ───────────────────────────────
            elapsed = t_now - self._sysid_start_t
            if elapsed >= self._sysid_duration_s:
                if not self._sysid_done:
                    print(f"[sysid] Complete — {self._sysid_index} steps logged → {self._sysid_filepath}")
                    self._sysid_done = True
                return

            # ── Advance PRBS index at sysid_freq_hz ──────────────────────────
            step_period = 1.0 / self._sysid_freq_hz
            if (t_now - self._sysid_last_switch_t) >= step_period:
                if self._sysid_index < len(self._sysid_seq_pan) - 1:
                    self._sysid_index += 1
                self._sysid_last_switch_t = t_now

            # ── Command mount ─────────────────────────────────────────────────
            cmd_pan  = self._sysid_base_pan  + self._sysid_seq_pan[self._sysid_index]
            cmd_tilt = self._sysid_base_tilt + self._sysid_seq_tilt[self._sysid_index]
            self._mount.set_position(cmd_pan, cmd_tilt)

            # ── Log: [pan_angular_disp, tilt_angular_disp, cmd_pan, cmd_tilt, t] ──
            self._write_control_graph(
                filename=self._sysid_filepath,
                dx_ang=angle_pan,
                dy_ang=angle_tilt,
                cmd_pan_ang=cmd_pan,
                cmd_tilt_ang=cmd_tilt,
            )

    def _log(self, msg: str) -> None:
        if self._debug:
            print(msg)

    def _log_banner(self, char: str, msg: str) -> None:
        if self._debug:
            bar = char * 88
            print(f"\n{bar}\n {msg}\n{bar}\n")
