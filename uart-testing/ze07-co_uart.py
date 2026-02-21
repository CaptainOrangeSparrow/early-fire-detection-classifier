import time
import serial

PORT = "/dev/ttyTHS1"
BAUD = 9600

# Commands from the manual (Tables 5/6/7)
CMD_SWITCH_TO_QA   = bytes([0xFF, 0x01, 0x78, 0x41, 0x00, 0x00, 0x00, 0x00, 0x46])  # Q&A mode
CMD_SWITCH_TO_PUSH = bytes([0xFF, 0x01, 0x78, 0x40, 0x00, 0x00, 0x00, 0x00, 0x47])  # initiative upload
CMD_ASK_READING    = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])  # query (same as MH-Z style)

def checksum_ok(frame9: bytes) -> bool:
    """
    Manual checksum: (~(Byte1+...+Byte7) + 1) & 0xFF equals Byte8
    """
    if len(frame9) != 9:
        return False
    s = sum(frame9[1:8]) & 0xFF
    cs = ((~s) + 1) & 0xFF
    return cs == frame9[8]

def read_frame9_resync(s: serial.Serial, timeout_s: float = 1.5) -> bytes | None:
    """
    Read a 9-byte frame, resyncing on 0xFF start byte.
    Works well for initiative-upload stream.
    """
    end = time.time() + timeout_s
    while time.time() < end:
        b = s.read(1)
        if not b:
            continue
        if b[0] != 0xFF:
            continue
        rest = s.read(8)
        if len(rest) != 8:
            continue
        frame = b + rest
        return frame
    return None

def parse_ze07_co(frame9: bytes) -> dict:
    """
    Supports:
      - Initiative upload (Table 4): [FF, gas, unit, decimals, conc_hi, conc_lo, range_hi, range_lo, cs]
      - Q&A reply (Table 8):        [FF, 86, conc_hi, conc_lo, 00, 00, range_hi, range_lo, cs]
    Returns ppm in float (0.1 ppm resolution) + metadata.
    """
    if len(frame9) != 9 or frame9[0] != 0xFF:
        raise ValueError("Not a 9-byte frame starting with 0xFF")

    mode = "unknown"
    if frame9[1] == 0x04 and frame9[2] == 0x03:  # CO type, ppm unit in the manual's initiative frame
        mode = "initiative_upload"
        decimals = frame9[3]
        conc_raw = (frame9[4] << 8) | frame9[5]
        full_raw = (frame9[6] << 8) | frame9[7]
    elif frame9[1] == 0x86:
        mode = "question_answer_reply"
        decimals = 1  # manual formula uses x0.1 for concentration
        conc_raw = (frame9[2] << 8) | frame9[3]
        full_raw = (frame9[6] << 8) | frame9[7]
    else:
        decimals = None
        conc_raw = None
        full_raw = None

    ppm = None
    if conc_raw is not None:
        # Manual: ppm = (hi*256 + lo) * 0.1
        ppm = conc_raw * 0.1

    return {
        "mode": mode,
        "ppm": ppm,
        "conc_raw": conc_raw,
        "full_range_raw": full_raw,
        "decimals_byte": decimals,
        "checksum_ok": checksum_ok(frame9),
        "hex": frame9.hex(),
    }

# -----------------------------
# Choose one:
#   MODE = "push"  -> default sensor behavior, just listen
#   MODE = "qa"    -> switch to Q&A then poll with CMD_ASK_READING
# -----------------------------
MODE = "qa"  # "push" or "qa"

with serial.Serial(PORT, BAUD, timeout=0.2) as s:
    print(f"Opened {PORT} @ {BAUD}")

    s.reset_input_buffer()
    s.reset_output_buffer()

    if MODE == "qa":
        # Put sensor into Q&A mode (it stops streaming and answers queries)
        s.write(CMD_SWITCH_TO_QA)
        s.flush()
        time.sleep(0.2)
        s.reset_input_buffer()
        print("Switched to Q&A mode")

    elif MODE == "push":
        # Optional: explicitly request initiative upload mode
        s.write(CMD_SWITCH_TO_PUSH)
        s.flush()
        time.sleep(0.2)
        s.reset_input_buffer()
        print("Listening for initiative upload frames (1 Hz)")

    while True:
        if MODE == "qa":
            s.reset_input_buffer()
            s.write(CMD_ASK_READING)
            s.flush()
            time.sleep(0.1)

        frame = read_frame9_resync(s, timeout_s=1.5)
        if frame is None:
            print("Timeout waiting for frame...")
            continue

        data = parse_ze07_co(frame)

        if not data["checksum_ok"]:
            print("BAD CS:", data["hex"])
            continue

        print(f'{data["mode"]}: CO={data["ppm"]:.1f} ppm  raw={data["conc_raw"]}  full={data["full_range_raw"]}  hex={data["hex"]}')
        time.sleep(0.3 if MODE == "qa" else 0.05)
