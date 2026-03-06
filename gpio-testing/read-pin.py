import Jetson.GPIO as GPIO
import time
GPIO.setmode(GPIO.BOARD)
GPIO.setup(7, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
time.sleep(2)
while True:
    print(GPIO.input(7))
    time.sleep(0.5)
