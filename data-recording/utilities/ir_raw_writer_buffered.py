from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

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


@dataclass(frozen=True)
class _IRChunk:
    start_idx: int
    end_idx: int
    n_frames: int
    frame_idx: np.ndarray  # (chunk_frames,) int64 (only first n_frames valid)
    t_sample: np.ndarray   # (chunk_frames,) float64 (only first n_frames valid)
    ir_raw16: np.ndarray   # (chunk_frames,H,W) uint16 (only first n_frames valid)


@dataclass
class _IRBuffer:
    """One preallocated chunk buffer."""
    frame_idx: np.ndarray  # (chunk_frames,) int64
    t_sample: np.ndarray   # (chunk_frames,) float64
    ir_raw16: np.ndarray   # (chunk_frames,H,W) uint16


class IrRawChunkWriterDoubleBuffer:
    """
    Double-buffered + background writer (NO COMPRESSION).

    Goals:
      - No per-frame list appends
      - No np.stack() at chunk boundaries
      - Disk I/O off the capture thread
      - Capture thread does only:
          * dtype/shape checks
          * np.copyto into preallocated array
          * cheap scalar writes
          * occasional buffer swap and queue put()

    Files written:
        ir_raw/ir_raw_000000_000249.npz

    Each NPZ contains:
      - frame_idx: (N,) int64
      - t_sample:  (N,) float64
      - ir_raw16:  (N,H,W) uint16
    """

    def __init__(
        self,
        recording_dir: str,
        meta: IRMeta,
        n_buffers: int = 3,
        filled_queue_max: int = 2,
    ):
        if n_buffers < 2:
            raise ValueError("n_buffers must be >= 2 for double buffering")

        self.meta = meta
        self.recording_dir = recording_dir

        if recording_dir is not None:
            self.ir_dir = os.path.join(recording_dir, "ir_raw")
            os.makedirs(self.ir_dir, exist_ok=True)
        else:
            self.ir_dir = None

        H, W = self.meta.ir_shape
        N = self.meta.chunk_frames

        # Pool of free (writable) buffers.
        self._free: "queue.Queue[_IRBuffer]" = queue.Queue(maxsize=n_buffers)
        for _ in range(n_buffers):
            buf = _IRBuffer(
                frame_idx=np.empty((N,), dtype=np.int64),
                t_sample=np.empty((N,), dtype=np.float64),
                ir_raw16=np.empty((N, H, W), dtype=np.uint16),
            )
            self._free.put(buf)

        # Queue of filled buffers waiting to be written.
        self._filled: "queue.Queue[Optional[_IRChunk]]" = queue.Queue(maxsize=filled_queue_max)

        self._writer_exc: Optional[BaseException] = None
        self._closed = False

        # Current buffer being filled by capture thread
        self._cur: _IRBuffer = self._free.get()
        self._cur_pos: int = 0
        self._first_frame_idx_in_chunk: Optional[int] = None

        # Dedicated IR writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="IrRawChunkWriterDoubleBuffer",
            daemon=True,
        )
        self._writer_thread.start()

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
                "compression": "none",
                "buffering": f"prealloc double-buffer (n_buffers>=2)",
            },
        }
        return meta_obj

    def append(self, frame_idx: int, t_sample: float, raw16: np.ndarray):
        if self._closed:
            raise RuntimeError("append() called after close()")

        if self.recording_dir is None or self.ir_dir is None:
            raise RuntimeError("Appending IR write frame but IR Raw Writer Recording Dir is None")

        # If writer died, fail fast so you don't silently lose data.
        if self._writer_exc is not None:
            raise RuntimeError(f"IR writer thread failed: {self._writer_exc}") from self._writer_exc

        if raw16 is None:
            return

        if raw16.dtype != np.uint16:
            raise ValueError(f"raw16 dtype must be uint16, got {raw16.dtype}")
        if raw16.shape != self.meta.ir_shape:
            raise ValueError(f"raw16 shape must be {self.meta.ir_shape}, got {raw16.shape}")

        if self._first_frame_idx_in_chunk is None:
            self._first_frame_idx_in_chunk = int(frame_idx)

        i = self._cur_pos
        self._cur.frame_idx[i] = int(frame_idx)
        self._cur.t_sample[i] = float(t_sample)
        # Fast copy into preallocated storage (decouples from upstream reuse/mutation)
        np.copyto(self._cur.ir_raw16[i], raw16)

        self._cur_pos += 1
        if self._cur_pos >= self.meta.chunk_frames:
            self.flush()

    def flush(self):
        """
        If current buffer has data, enqueue it for writer and swap to a free buffer.

        This may block if:
          - filled queue is full (writer can't keep up), or
          - no free buffer is available (all buffers are being written/queued).
        """
        if self._cur_pos == 0:
            return

        if self.recording_dir is None or self.ir_dir is None:
            raise RuntimeError("Flushing IR write frame but IR Raw Writer Recording Dir is None")

        if self._writer_exc is not None:
            raise RuntimeError(f"IR writer thread failed: {self._writer_exc}") from self._writer_exc

        n = self._cur_pos
        start_idx = (
            self._first_frame_idx_in_chunk
            if self._first_frame_idx_in_chunk is not None
            else int(self._cur.frame_idx[0])
        )
        end_idx = int(self._cur.frame_idx[n - 1])

        chunk = _IRChunk(
            start_idx=int(start_idx),
            end_idx=int(end_idx),
            n_frames=int(n),
            frame_idx=self._cur.frame_idx,
            t_sample=self._cur.t_sample,
            ir_raw16=self._cur.ir_raw16,
        )

        # Enqueue filled chunk for writer (backpressure if writer is slow)
        if self._filled.full():
            print("WARNING: IR writer queue full - wating for disk writer")
        self._filled.put(chunk)

        # Swap to a new free buffer (backpressure if none are free yet)
        if self._free.empty():
            print("WARNING: IR writer waiting for free buffer (writer may be slow)")
        self._cur = self._free.get()
        self._cur_pos = 0
        self._first_frame_idx_in_chunk = None

    def _writer_loop(self):
        try:
            while True:
                item = self._filled.get()
                try:
                    if item is None:
                        return  # sentinel

                    assert self.ir_dir is not None
                    out_name = f"ir_raw_{item.start_idx:06d}_{item.end_idx:06d}.npz"
                    out_path = os.path.join(self.ir_dir, out_name)

                    n = item.n_frames

                    # Write only the valid prefix (N can be < chunk_frames for final chunk)
                    # NO COMPRESSION:
                    np.savez(
                        out_path,
                        frame_idx=item.frame_idx[:n].copy(),  # copy to shrink to (n,)
                        t_sample=item.t_sample[:n].copy(),
                        ir_raw16=item.ir_raw16[:n].copy(),    # copy to shrink to (n,H,W)
                    )

                    # Return the underlying buffer to the free pool so capture can reuse it.
                    self._free.put(_IRBuffer(item.frame_idx, item.t_sample, item.ir_raw16))

                finally:
                    self._filled.task_done()

        except BaseException as e:
            self._writer_exc = e

    def close(self):
        """
        Flush partial chunk, wait for pending writes, and stop writer thread.

        Call this once at end of recording.
        """
        if self._closed:
            return
        self._closed = True

        # enqueue any partially filled buffer
        self.flush()

        # wait for all queued chunks to be written
        self._filled.join()

        # stop writer
        self._filled.put(None)
        self._writer_thread.join(timeout=5.0)

        if self._writer_exc is not None:
            raise RuntimeError(f"IR writer thread failed: {self._writer_exc}") from self._writer_exc
