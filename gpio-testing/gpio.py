import gpiod
import time

chip = gpiod.Chip("gpiochip0")
line = chip.get_line(85)

line.request(consumer="conda_gpio", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])

print("GPIO is HIGH")

try:
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    pass

finally:
    line.release()



