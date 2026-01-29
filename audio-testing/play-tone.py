import argparse
import numpy as np
import sounddevice as sd
import time

parser = argparse.ArgumentParser()
parser.add_argument("--freq", type=float, default=1000)
parser.add_argument("--time", type=float, default=2.0)
parser.add_argument("--amp", type=float, default=0.3)
parser.add_argument("--device", type=int, default=None)  # let ALSA default if None
args = parser.parse_args()

fs = 48000
n = int(fs * args.time)
t = np.arange(n) / fs
sig = (args.amp * np.sin(2*np.pi*args.freq*t)).astype(np.float32)
stereo = np.column_stack([sig, sig])

print(f"Playing {args.freq} Hz for {args.time} s, samples={n}, device={args.device}")

with sd.OutputStream(samplerate=fs, channels=2, dtype="float32", device=args.device) as stream:
    stream.write(stereo)
    stream.stop()

# Keep process alive briefly (helps if backend buffers oddly)
time.sleep(0.1)

