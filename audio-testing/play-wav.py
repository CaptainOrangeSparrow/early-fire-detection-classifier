import argparse
import numpy as np
import sounddevice as sd
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("wav")
parser.add_argument("--device", type=int, default=None)
parser.add_argument("--volume", type=float, default=1.0,
                    help="Linear volume multiplier (0.0–1.0, can exceed but may clip)")
args = parser.parse_args()

data, fs = sf.read(args.wav, dtype="float32")

# ensure stereo
if data.ndim == 1:
    data = data[:, None]
if data.shape[1] == 1:
    data = np.repeat(data, 2, axis=1)

# apply volume
data = data * args.volume

# hard clip to valid float32 audio range
np.clip(data, -1.0, 1.0, out=data)

sd.play(data, fs, device=args.device)
sd.wait()

