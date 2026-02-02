import CameraMount2Axis

if __name__ == "__main__":
    # Jetson Nano BOARD pins with PWM support
    PAN_PIN = 33
    TILT_PIN = 32

    mount = CameraMount2Axis(PAN_PIN, TILT_PIN)

    try:
        mount.center()
        time.sleep(1)

        mount.set_position(45, 120)
        time.sleep(1)

        mount.set_position(135, 60)
        time.sleep(1)

    finally:
        mount.shutdown()
