import math
from .CameraMount2Axis import CameraMount2Axis
from .pid import PID


# Camera resolution 
FRAME_W = 640   # pixels
FRAME_H = 480   # pixels

# Camera field of view 
# From camera datasheet: 56° × 42° (horizontal × vertical).
# The angular error formula requires the HALF-FOV angle (θ) in radians:
#
#   φ = tan⁻¹( 2x · tan(θ) / b )
#
# where x  = pixel offset from frame center (signed),
#       θ  = half-FOV for that axis (radians),
#       b  = total frame dimension in pixels for that axis,
#       φ  = angular displacement from boresight (degrees, output).
#
# https://stackoverflow.com/a/tagged/camera-fov (right-triangle derivation)

HFOV_DEG = 56.0                                # full horizontal FOV (degrees)
VFOV_DEG = 42.0                                # full vertical   FOV (degrees)

# radians for atan2() in pixel_to_angle() for pan axis
HALF_HFOV_RAD = math.radians(HFOV_DEG / 2.0)  
HALF_VFOV_RAD = math.radians(VFOV_DEG / 2.0) 

# GPIO pins
PAN_PIN  = 33
TILT_PIN = 32

# Mount angle limits
PAN_LIMITS  = (0.0, 180.0)
TILT_LIMITS = (0.0, 135.0)

"""
Tuning order:
    1. Set kI = kD = 0. Raise kP until the mount oscillates.
        Then halve kP.
    2. Raise kI until drift is eliminated.
    3. Raise kD until overshoot is damped.
"""

# PID gains
PAN_KP,  PAN_KI,  PAN_KD  = 0.07, 0.005, 0   # 0.02, 0.02
TILT_KP, TILT_KI, TILT_KD = 0.2, 0.004, 0   # 0.015, 0.015

# Error sign convention for positve angular error corrections
PAN_ERROR_SIGN  = -1 # positive because pixel x increases to the right, and positive pan correction should move the camera right
TILT_ERROR_SIGN = +1 # negative because pixel y increases downwards, but positive tilt correction should move the camera up


def pixel_to_angle(pixel_offset: float, half_fov_rad: float, frame_dim: int) -> float:
    """
    Convert a signed pixel offset from frame center into an angular
    displacement from the camera center, using the exact right-triangle
    derivation.

    Formula:    φ = tan⁻¹( 2x · tan(θ) / b )

    pixel_offset:  Signed pixel distance from frame center.
                    Positive → right (pan) / down (tilt); negative → left (pan) / up (tilt).
                    
    half_fov_rad:  Half the field-of-view for this axis, in radians.
                    
    frame_dim:     Total frame size in pixels for this axis (b in formula).

    Returns:
        Angular displacement φ in degrees.
        Range: (−half_fov_deg, +half_fov_deg) clamped by the camera's FOV.
    """
    return math.degrees(
        math.atan2(2.0 * pixel_offset * math.tan(half_fov_rad), frame_dim)
    )


def build_mount() -> CameraMount2Axis:
    return CameraMount2Axis(
        pan_pin=PAN_PIN,
        tilt_pin=TILT_PIN,
        transition_type='s-curve',
        transition_speed=5.0,
        pan_limits=PAN_LIMITS,
        tilt_limits=TILT_LIMITS,
        update_rate_hz=50.0
    )


def build_pids():
    pid_pan  = PID(kP=PAN_KP,  kI=PAN_KI,  kD=PAN_KD, minOutput=-HFOV_DEG, maxOutput=HFOV_DEG)
    pid_tilt = PID(kP=TILT_KP, kI=TILT_KI, kD=TILT_KD, minOutput=-VFOV_DEG, maxOutput=VFOV_DEG)
    pid_pan.initialize(difference_equation=True)
    pid_tilt.initialize(difference_equation=True)
    return pid_pan, pid_tilt