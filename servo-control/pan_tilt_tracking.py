"""
pan_tilt_tracking.py
====================
Single-threaded fire-tracking driver for the Smart Autonomous Early Fire
Detection System (Jetson Orin Nano).

Architecture
------------
One tight main loop drives everything sequentially:

    1. Grab visible + IR frames from your camera pipeline.
    2. Run process_fused_detection() → results dict.
    3. ObjCenter parses the box from meta_decision.
    4a. Fire detected  → stop scan, PID centres the mount on the fire box.
    4b. No fire        → start/resume raster scan.

No multiprocessing is used — the detection pipeline already runs fast enough
that a single thread is clean and easy to reason about.

TODOs are clearly marked.  Fill them in before running.
"""

# ── Standard imports ──────────────────────────────────────────────────────────
import math
import signal
import sys
import time

# ── Project imports ───────────────────────────────────────────────────────────
from CameraMount2Axis import CameraMount2Axis
from objcenter import ObjCenter
from pid import PID

# TODO: replace with your actual detection module import
# from your_detection_module import process_fused_detection, load_models

# =============================================================================
# Configuration — edit these constants to match your hardware / preferences
# =============================================================================

# ── Camera resolution (visible sensor) ───────────────────────────────────────
FRAME_W = 640   # pixels
FRAME_H = 480   # pixels

# ── Camera field of view ──────────────────────────────────────────────────────
# From camera datasheet: 56° × 42° (horizontal × vertical).
# The angular error formula requires the HALF-FOV angle (θ) in radians:
#
#   φ = tan⁻¹( 2x · tan(θ) / b )
#
# where x  = pixel offset from frame centre (signed),
#       θ  = half-FOV for that axis (radians),
#       b  = total frame dimension in pixels for that axis,
#       φ  = angular displacement from boresight (degrees, output).
#
# Source: https://stackoverflow.com/a/tagged/camera-fov (right-triangle derivation)
HFOV_DEG = 56.0                                # full horizontal FOV (degrees)
VFOV_DEG = 42.0                                # full vertical   FOV (degrees)
HALF_HFOV_RAD = math.radians(HFOV_DEG / 2.0)  # θ for pan  axis
HALF_VFOV_RAD = math.radians(VFOV_DEG / 2.0)  # θ for tilt axis

# ── GPIO pins (Jetson BOARD numbering) ───────────────────────────────────────
PAN_PIN  = 33
TILT_PIN = 35

# ── Mount angle limits (degrees, 0–180) ──────────────────────────────────────
PAN_LIMITS  = (0.0,  180.0)   # (min, max)
TILT_LIMITS = (90.0, 180.0)   # (min, max)

# ── PID gains ────────────────────────────────────────────────────────────────
# With angular error, kP ≈ 1.0 is a reasonable starting point.
# A kP of 1.0 means a 10° angular offset produces a 10° servo correction.
#
# Tuning steps:
#   1. Set kI = kD = 0.  Increase kP until the mount oscillates steadily,
#      then halve kP.
#   2. Increase kI until steady-state offset disappears.
#   3. Increase kD until overshoot is damped.
PAN_KP,  PAN_KI,  PAN_KD  = 1.0, 0.0, 0.0
TILT_KP, TILT_KI, TILT_KD = 1.0, 0.0, 0.0

# ── Error sign convention ─────────────────────────────────────────────────────
# Defines the physical direction a positive angular error maps to.
#
# PAN_ERROR_SIGN:
#   +1 → fire to the RIGHT means pan angle should INCREASE.
#   -1 → invert if your mount pans the opposite direction.
#
# TILT_ERROR_SIGN:
#   -1 → fire BELOW centre means tilt angle should DECREASE.
#   +1 → invert if your mount tilts the opposite direction.
PAN_ERROR_SIGN  = +1
TILT_ERROR_SIGN = -1

# ── Raster scan parameters ────────────────────────────────────────────────────
SCAN_DURATION  = 45.0   # seconds per full sweep (adjust 30–60)
SCAN_TILT_ROWS = 5      # number of tilt levels in the grid
SCAN_PAN_COLS  = 9      # number of pan stops per row

# =============================================================================
# Angular error helper
# =============================================================================

def pixel_to_angle(pixel_offset: float, half_fov_rad: float, frame_dim: int) -> float:
    """
    Convert a signed pixel offset from frame centre into an angular
    displacement from the camera center, using the exact right-triangle
    derivation.

    Formula:    φ = tan⁻¹( 2x · tan(θ) / b )

    Args:
        pixel_offset:  Signed pixel distance from frame centre.
                       Positive → right / down; negative → left / up.
        half_fov_rad:  Half the field-of-view for this axis, in radians.
                       e.g. math.radians(56/2) for horizontal.
        frame_dim:     Total frame size in pixels for this axis (b in formula).

    Returns:
        Angular displacement φ in degrees.
        Range: (−half_fov_deg, +half_fov_deg)
    """
    return math.degrees(
        math.atan2(2.0 * pixel_offset * math.tan(half_fov_rad), frame_dim)
    )


# =============================================================================
# Initialisation
# =============================================================================

def build_mount() -> CameraMount2Axis:
    return CameraMount2Axis(
        pan_pin=PAN_PIN,
        tilt_pin=TILT_PIN,
        transition_type='instant',       # instant for PID; scan uses same
        transition_speed=5.0,          # not used for 'instant', but required
        pan_limits=PAN_LIMITS,
        tilt_limits=TILT_LIMITS,
        update_rate_hz=50.0
    )


def build_pids():
    pid_pan  = PID(kP=PAN_KP,  kI=PAN_KI,  kD=PAN_KD)
    pid_tilt = PID(kP=TILT_KP, kI=TILT_KI, kD=TILT_KD)
    pid_pan.initialize()
    pid_tilt.initialize()
    return pid_pan, pid_tilt


def signal_handler(sig, frame):
    """Graceful Ctrl-C shutdown — called from the except block below too."""
    print("\n[INFO] Interrupt received — shutting down.")
    sys.exit(0)


# =============================================================================
# Main loop
# =============================================================================

def main():
    signal.signal(signal.SIGINT, signal_handler)

    # ── Hardware setup ────────────────────────────────────────────────────────
    print("[INFO] Initialising camera mount...")
    mount = build_mount()

    print("[INFO] Initialising PID controllers...")
    pid_pan, pid_tilt = build_pids()

    print("[INFO] Initialising object centre finder...")
    obj_finder = ObjCenter(frame_w=FRAME_W, frame_h=FRAME_H)

    # ── TODO: load your detection models ─────────────────────────────────────
    # print("[INFO] Loading detection models...")
    # models = load_models(...)

    # ── TODO: open your camera streams ───────────────────────────────────────
    # vs_visible  = ...   # visible camera stream
    # vs_infrared = ...   # infrared camera stream

    # ── Begin scanning immediately (no fire yet) ──────────────────────────────
    print("[INFO] Starting initial raster scan...")
    mount.start_scan(
        duration=SCAN_DURATION,
        tilt_steps=SCAN_TILT_ROWS,
        pan_steps=SCAN_PAN_COLS
    )

    print("[INFO] Entering main tracking loop. Press Ctrl-C to quit.")

    try:
        while True:
            # ── 1. Grab frames ────────────────────────────────────────────────
            # TODO: replace with your actual frame acquisition
            # frame_v = vs_visible.read()    # visible numpy array (H, W, 3)
            # frame_i = vs_infrared.read()   # infrared numpy array (H, W, ...)

            # ── 2. Run fused detection ────────────────────────────────────────
            # TODO: uncomment once models and frames are wired up
            # results = process_fused_detection(frame_v, frame_i, models)

            # ── STUB: remove when real detection is wired ─────────────────────
            results = {'meta_decision': {'fire_detection_boolean': False}}
            # ─────────────────────────────────────────────────────────────────

            # ── 3. Parse results for object location ──────────────────────────
            (obj_x, obj_y), (cx, cy), fire_detected = obj_finder.update(results)

            # ── 4a. Fire found — PID tracking ─────────────────────────────────
            if fire_detected:
                if mount.is_scanning():
                    print("[INFO] Fire detected — stopping scan, locking on.")
                    mount.stop_scan()
                    # Re-initialise integrators so stale scan state doesn't
                    # cause a sudden jump when we switch to tracking.
                    pid_pan.initialize()
                    pid_tilt.initialize()

                # Angular displacement error (degrees) from boresight.
                # φ = tan⁻¹( 2x · tan(θ) / b )
                # Positive error_pan  → fire is to the RIGHT of boresight.
                # Positive error_tilt → fire is BELOW boresight.
                error_pan  = PAN_ERROR_SIGN  * pixel_to_angle(
                    obj_x - cx, HALF_HFOV_RAD, FRAME_W
                )
                error_tilt = TILT_ERROR_SIGN * pixel_to_angle(
                    obj_y - cy, HALF_VFOV_RAD, FRAME_H
                )

                pan_delta  = pid_pan.update(error_pan)
                tilt_delta = pid_tilt.update(error_tilt)

                new_pan  = mount.get_pan()  + pan_delta
                new_tilt = mount.get_tilt() + tilt_delta
                mount.set_position(new_pan, new_tilt)

            # ── 4b. No fire — ensure raster scan is running ───────────────────
            else:
                if not mount.is_scanning():
                    print("[INFO] Fire lost — resuming raster scan.")
                    mount.start_scan(
                        duration=SCAN_DURATION,
                        tilt_steps=SCAN_TILT_ROWS,
                        pan_steps=SCAN_PAN_COLS
                    )

    except (KeyboardInterrupt, SystemExit):
        pass

    finally:
        print("[INFO] Stopping scan and shutting down mount...")
        mount.stop_scan()
        mount.shutdown(center=True)
        print("[INFO] Done.")


if __name__ == "__main__":
    main()