import serial
import time

# ===== CONFIG =====
PORT = "/dev/ttyUSB1"   # change as needed
BAUD = 115200

# ===== SETUP =====
ser = serial.Serial(PORT, BAUD, timeout=0.1)

def send_servos(us1, us2):
    # Clamp values
    us1 = max(500, min(2500, int(us1)))
    us2 = max(500, min(2500, int(us2)))

    # Pack into little-endian bytes
    b2 = us1 & 0xFF
    b3 = (us1 >> 8) & 0xFF
    b4 = us2 & 0xFF
    b5 = (us2 >> 8) & 0xFF

    checksum = (b2 + b3 + b4 + b5) & 0xFF

    packet = bytes([0xAA, 0x55, b2, b3, b4, b5, checksum])
    ser.write(packet)


# ===== TEST LOOP =====
try:
    while True:
        # Example: sweep servo 1, hold servo 2
        for val in range(500, 2500, 5):
            send_servos(val, 1500)
            time.sleep(0.02)  # 50 Hz update

        for val in range(2500, 500, -5):
            send_servos(val, 1500)
            time.sleep(0.02)

except KeyboardInterrupt:
    print("Stopping...")
    ser.close()
