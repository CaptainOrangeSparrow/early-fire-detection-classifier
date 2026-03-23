# peripherals/gst_nvenc_writer.py
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)

class GstNvencMp4Writer:
    """
    Push BGR frames from Python into NVENC H.264 MP4.
    You provide pts_ns so you can keep perfect alignment with CSV ticks.
    """
    def __init__(self, out_mp4, w, h, fps, bitrate=8_000_000):
        self.out_mp4 = out_mp4
        self.w, self.h, self.fps = int(w), int(h), int(fps)
        self.bitrate = int(bitrate)

        self.pipeline_str = f"""
            appsrc name=src is-live=true format=time do-timestamp=false !
            video/x-raw,format=BGR,width={self.w},height={self.h},framerate={self.fps}/1 !
            videoconvert !
            nvvidconv ! video/x-raw(memory:NVMM),format=NV12,width={self.w},height={self.h},framerate={self.fps}/1 !
            nvv4l2h264enc bitrate={self.bitrate} iframeinterval={self.fps} insert-sps-pps=true !
            h264parse ! qtmux !
            filesink location={self.out_mp4} sync=false
        """
        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.appsrc = self.pipeline.get_by_name("src")
        self._dur_ns = int(1e9 / self.fps)
        self._started = False

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True

    def write(self, frame_bgr: np.ndarray, pts_ns: int):
        if not self._started:
            raise RuntimeError("Writer not started")
        if frame_bgr is None:
            return
        if frame_bgr.dtype != np.uint8 or frame_bgr.shape != (self.h, self.w, 3):
            raise ValueError(f"Expected uint8 frame {(self.h, self.w, 3)}, got {frame_bgr.dtype} {frame_bgr.shape}")

        data = frame_bgr.tobytes()
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        buf.pts = int(pts_ns)
        buf.dts = int(pts_ns)
        buf.duration = self._dur_ns

        ret = self.appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            raise RuntimeError(f"push-buffer failed: {ret}")

    def stop(self):
        if not self._started:
            return
        try:
            self.appsrc.emit("end-of-stream")
        except Exception:
            pass
        self.pipeline.set_state(Gst.State.NULL)
        self._started = False
