import time, binascii
import serial

PORT = "/dev/ttyUSB0"
BAUD = 9600
CMD  = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])

def read_exact(s, n, timeout_s=0.5):
    end = time.time() + timeout_s
    buf = bytearray()
    while len(buf) < n and time.time() < end:
        chunk = s.read(n - len(buf))
        if chunk:
            buf.extend(chunk)
    return bytes(buf)

with serial.Serial(PORT, BAUD, timeout=0.1) as s:
    print("Opened:", PORT, "baud", BAUD)

    while True:
        # flush anything old
        s.reset_input_buffer()

        # send command
        s.write(CMD)
        s.flush()
        print("TX:", CMD.hex())

        # give sensor a moment
        time.sleep(0.10)

        # try to read a full 9-byte frame
        rx = read_exact(s, 9, timeout_s=0.5)

        # if not full, read whatever is left
        if len(rx) < 9:
            time.sleep(0.10)
            more = s.read(64)
            rx += more

        print("RX len:", len(rx), "data:", binascii.hexlify(rx).decode())
        time.sleep(0.5)

