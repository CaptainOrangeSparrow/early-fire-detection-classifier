from class_telemetry import Telemetry
import time

if __name__ == "__main__":
    try:
        telemetry = Telemetry()
        while True:
            telemetry.execute()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        telemetry.display.cleanup()
