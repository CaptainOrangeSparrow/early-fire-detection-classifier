import Jetson.GPIO as GPIO
import Jetson.GPIO.gpio_pin_data as pd
import pprint

GPIO.setmode(GPIO.BOARD)

model, info, ch_data = pd.get_data()

print("MODEL:", model)
print("\nJETSON_INFO keys:", list(info.keys()) if hasattr(info, "keys") else type(info))

print("\nch_data type:", type(ch_data))
if hasattr(ch_data, "keys"):
    print("ch_data keys:", list(ch_data.keys()))
else:
    print("ch_data is not a dict; repr:")
    print(repr(ch_data))

print("\nFull ch_data (truncated pretty print):")
pprint.pprint(ch_data)
