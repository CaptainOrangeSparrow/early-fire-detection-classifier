import Jetson.GPIO as GPIO
import Jetson.GPIO.gpio_pin_data as pd

model, info, ch_data = pd.get_data()
board = ch_data["BOARD"]

pins = [15, 16, 29, 31]
for p in pins:
    ch = board[p]
    # ChannelInfo objects usually have a useful repr; print everything we can
    print(f"\nBOARD {p}:")
    for attr in ["pin", "gpio", "gpio_name", "linux_pin", "chip", "line", "soc", "soc_gpio", "soc_pin", "pinctrl", "pinctrl_name"]:
        if hasattr(ch, attr):
            print(f"  {attr}: {getattr(ch, attr)}")
    # fallback: dump __dict__ if present
    if hasattr(ch, "__dict__"):
        print("  __dict__:", ch.__dict__)
    else:
        print("  (no __dict__) repr:", ch)
