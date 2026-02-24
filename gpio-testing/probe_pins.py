import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)

pins = {
    15: "want OUTPUT",
    29: "want OUTPUT",
    31: "want OUTPUT",
    16: "want INPUT",
}

for p, goal in pins.items():
    try:
        if "OUTPUT" in goal:
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
        else:
            GPIO.setup(p, GPIO.IN)
        print(f"Pin {p}: setup OK ({goal})")
    except Exception as e:
        print(f"Pin {p}: ERROR: {e}")

GPIO.cleanup()
