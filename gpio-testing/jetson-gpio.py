import Jetson.GPIO as GPIO
import time

PIN = 15  # physical pin number

GPIO.setmode(GPIO.BOARD)   # use physical pin numbering
GPIO.setup(PIN, GPIO.OUT, initial=GPIO.LOW)

try:
    while True:
        GPIO.output(PIN, GPIO.HIGH)
        time.sleep(5)
        GPIO.output(PIN, GPIO.LOW)
        time.sleep(5)

except KeyboardInterrupt:
    pass

finally:
    GPIO.cleanup()

