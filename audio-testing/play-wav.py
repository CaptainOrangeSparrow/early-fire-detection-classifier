import argparse
import numpy as np
import sounddevice as sd
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("wav")
parser.add_argument("--device", type=int, default=None)  # use sd.query_devices() to pick
args = parser.parse_args()

data, fs = sf.read(args.wav, dtype="float32")

# ensure 2ch (many ALSA paths expect stereo)
if data.ndim == 1:
    data = data[:, None]
if data.shape[1] == 1:
    data = np.repeat(data, 2, axis=1)

sd.play(data, fs, device=args.device)
sd.wait()

