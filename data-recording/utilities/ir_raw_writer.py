# utilities/ir_raw_writer.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class IRMeta:
    fps_target: float
    ir_shape: Tuple[int, int] = (192, 256)
    ir_dtype: str = "uint16"
    conversion: str = "temp_c = raw/64.0 - 273.15"
    colormap: str = "JET"
    display_scale: int = 3
    chunk_frames: int = 250  # 10s @ 25 fps


class IrRawChunkWriter:
    """
    Buffers IR raw16 frames and writes them in compressed .npz chunks:

        ir_raw/ir_raw_000000_000249.npz

    Each NPZ contains:
      - frame_idx: (N,) int64
      - t_sample:  (N,) float64  (perf_counter timestamps)
      - ir_raw16:  (N,H,W) uint16

    Alignment strategy:
      - Join on frame_idx (exact), or use t_sample (float perf_counter timebase)
    """

    def __init__(
        self,
        recording_dir: str,
        meta: IRMeta,
    ):
        self.meta = meta
        self.recording_dir = recording_dir
        if recording_dir is not None:
            self.ir_dir = os.path.join(recording_dir, "ir_raw")
            os.makedirs(self.ir_dir, exist_ok=True)

        self._buf_frame_idx: List[int] = []
        self._buf_t_sample: List[float] = []
        self._buf_raw16: List[np.ndarray] = []

        self._first_frame_idx_in_chunk: Optional[int] = None

    def get_meta_info(self):
        meta_obj = {
            "fps_target": float(self.meta.fps_target),
            "ir_data": {
                "raw_shape": list(self.meta.ir_shape),
                "raw_dtype": self.meta.ir_dtype,
                "conversion": self.meta.conversion,
                "colormap": self.meta.colormap,
                "display_scale": float(self.meta.display_scale),
            },
            "ir_npz": {
                "chunk_frames": int(self.meta.chunk_frames),
                "dir": "ir_raw" if self.recording_dir is not None else "none (preview only)",
                "pattern": "ir_raw_%06d_%06d.npz",
                "arrays": ["frame_idx", "t_sample", "ir_raw16"],
            },
        }
        return meta_obj

    def append(self, frame_idx: int, t_sample: float, raw16: np.ndarray):

        if self.recording_dir is None:
            raise RuntimeError("Appending IR write frame but IR Raw Writer Recording Dir is None")

        """
        raw16 must be uint16 array of shape (H,W) == meta.ir_shape.
        """
        if raw16 is None:
            return

        if raw16.dtype != np.uint16:
            raise ValueError(f"raw16 dtype must be uint16, got {raw16.dtype}")

        if raw16.shape != self.meta.ir_shape:
            raise ValueError(f"raw16 shape must be {self.meta.ir_shape}, got {raw16.shape}")

        if self._first_frame_idx_in_chunk is None:
            self._first_frame_idx_in_chunk = int(frame_idx)

        self._buf_frame_idx.append(int(frame_idx))
        self._buf_t_sample.append(float(t_sample))
        # copy to decouple from any reuse/mutation upstream
        self._buf_raw16.append(raw16.copy())

        if len(self._buf_frame_idx) >= self.meta.chunk_frames:
            self.flush()

    def flush(self):
        if not self._buf_frame_idx:
            return
        
        if self.recording_dir is None:
            raise RuntimeError("Flushing IR write frame but IR Raw Writer Recording Dir is None")

        start_idx = self._first_frame_idx_in_chunk if self._first_frame_idx_in_chunk is not None else self._buf_frame_idx[0]
        end_idx = self._buf_frame_idx[-1]

        frame_idx_arr = np.asarray(self._buf_frame_idx, dtype=np.int64)
        t_sample_arr = np.asarray(self._buf_t_sample, dtype=np.float64)
        ir_raw16_arr = np.stack(self._buf_raw16, axis=0).astype(np.uint16, copy=False)  # (N,H,W)

        out_name = f"ir_raw_{start_idx:06d}_{end_idx:06d}.npz"
        out_path = os.path.join(self.ir_dir, out_name)

        # np.savez_compressed uses zip/deflate; reasonable size reduction, moderate CPU.
        np.savez_compressed(
            out_path,
            frame_idx=frame_idx_arr,
            t_sample=t_sample_arr,
            ir_raw16=ir_raw16_arr,
        )

        # reset buffers
        self._buf_frame_idx.clear()
        self._buf_t_sample.clear()
        self._buf_raw16.clear()
        self._first_frame_idx_in_chunk = None

    def close(self):
        self.flush()

