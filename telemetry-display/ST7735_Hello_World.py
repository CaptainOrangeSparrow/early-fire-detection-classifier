from PIL import Image
import st7735
import time

print("Initializing display...")

try:
    disp = st7735.ST7735(
        port=0, 
        cs=0, 
        dc="GPIO24",
        backlight=None, 
        rst="GPIO25",
        width=128, 
        height=160, 
        rotation=0, 
        invert=False,
	offset_left=0,
	offset_top=0,
	spi_speed_hz=32000000
    )
    print("Display initialized successfully")
except Exception as e:
    print(f"Error initializing display: {e}")
    exit(1)

print(f"Display size: {disp.width}x{disp.height}")

# Test 1: Solid RED
print("Displaying RED...")
img = Image.new('RGB', (128, 160), color=(255, 0, 0))
disp.display(img)
time.sleep(3)

# Test 2: Solid GREEN
print("Displaying GREEN...")
img = Image.new('RGB', (128, 160), color=(0, 255, 0))
disp.display(img)
time.sleep(3)

# Test 3: Solid BLUE
print("Displaying BLUE...")
img = Image.new('RGB', (128, 160), color=(0, 0, 255))
disp.display(img)
time.sleep(3)

# Test 4: WHITE
print("Displaying WHITE...")
img = Image.new('RGB', (128, 160), color=(255, 255, 255))
disp.display(img)

print("Test complete!")
