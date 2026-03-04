# peripherals/gst_capture.py
"""
GStreamer (gi) capture backends for Jetson.

Includes:
  - GstRgbCapture: USB RGB camera (MJPG) -> nvjpegdec -> appsink(BGR), optional tee to NVENC MP4.
  - GstIrCaptureRawYuy2: IR camera raw capture (YUY2) -> appsink, returns ndarray (H, W, 2) uint8.

Notes:
- Requires: python3-gi, GStreamer plugins, and on Jetson: nvjpegdec, nvvidconv, nvv4l2h264enc.
- These classes are designed to be polled ("get_latest") and to keep only the latest frame (drop/leaky).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)


@dataclass(frozen=True)
class CaptureFrame:
    frame: np.ndarray
    pts_ns: Optional[int]


class _LatestFrameStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._pts_ns: Optional[int] = None

    def set(self, frame: np.ndarray, pts_ns: Optional[int]) -> None:
        # Always copy so the Gst buffer can be released safely
        with self._lock:
            self._frame = frame.copy()
            self._pts_ns = pts_ns

    def get(self) -> Tuple[Optional[np.ndarray], Optional[int]]:
        with self._lock:
            if self._frame is None:
                return None, None
            return self._frame.copy(), self._pts_ns


class GstRgbCapture:
    """
    USB RGB MJPG capture using:
      v4l2src (do-timestamp=true) -> image/jpeg -> jpegparse -> nvjpegdec ->
      nvvidconv(NVMM NV12) -> (optional tee to NVENC MP4) -> appsink (BGR)

    If tee=True:
      - record branch encodes with nvv4l2h264enc to MP4
      - preview/ML branch returns latest BGR frame via appsink

    If tee=False:
      - just returns latest BGR frame via appsink
    """

    def __init__(
        self,
        device: str = "/dev/video0",
        w: int = 1280,
        h: int = 720,
        fps: int = 30,
        *,
        tee: bool = False,
        out_mp4: Optional[str] = None,
        bitrate: int = 8_000_000,
        drop_preview: bool = True,
    ):
        self.w, self.h, self.fps = int(w), int(h), int(fps)
        self.device = device
        self.tee = bool(tee)
        self.out_mp4 = out_mp4
        self.bitrate = int(bitrate)
        self.drop_preview = bool(drop_preview)

        self._store = _LatestFrameStore()


        tee_decl = ""
        record_branch = ""
        preview_branch = ""

        if self.tee:
            if not self.out_mp4:
                raise ValueError("GstRgbCapture: tee=True requires out_mp4 path.")
            tee_decl = "tee name=t"
            record_branch = f"""
                t. ! queue !
                nvv4l2h264enc bitrate={self.bitrate} iframeinterval={self.fps} insert-sps-pps=true !
                h264parse ! qtmux !
                filesink location={self.out_mp4} sync=false
            """
            # Preview branch taps from tee pad
            preview_branch = f"""
                t. ! queue leaky=downstream max-size-buffers=1 !
                nvvidconv ! video/x-raw,format=BGRx,width={self.w},height={self.h} !
                appsink name=appsink emit-signals=true drop=true max-buffers=1 sync=false
            """
            # before appsink, there was videoconvert ! video/x-raw,format=BGR
        else:
            # No tee: continue directly from the main chain
            preview_branch = f"""
                queue leaky=downstream max-size-buffers=1 !
                nvvidconv ! video/x-raw,format=BGRx,width={self.w},height={self.h} !
                videoconvert ! video/x-raw,format=BGR !
                appsink name=appsink emit-signals=true drop=true max-buffers=1 sync=false
            """

        self.pipeline_str = f"""
            v4l2src device={self.device} do-timestamp=true !
            image/jpeg,width={self.w},height={self.h},framerate={self.fps}/1 !
            jpegparse ! nvjpegdec !
            nvvidconv ! video/x-raw(memory:NVMM),format=NV12,width={self.w},height={self.h},framerate={self.fps}/1 !
            {tee_decl}
            {record_branch}
            {preview_branch}
        """

        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.appsink = self.pipeline.get_by_name("appsink")
        self.appsink.connect("new-sample", self._on_new_sample)
        self._started = False

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        pts = buf.pts
        pts_ns: Optional[int] = None if pts == Gst.CLOCK_TIME_NONE else int(pts)

        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK

        try:
            arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
            # BGR: 3 bytes/pixel
            frame = arr.reshape((self.h, self.w, 3))
            self._store.set(frame, pts_ns)
        finally:
            buf.unmap(mapinfo)

        return Gst.FlowReturn.OK

    def start(self) -> None:
        if self._started:
            return
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        # EOS helps finalize mp4 if tee-recording is enabled
        try:
            self.pipeline.send_event(Gst.Event.new_eos())
        except Exception:
            pass
        self.pipeline.set_state(Gst.State.NULL)
        self._started = False

    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[int]]:
        """
        Returns (frame_bgr, pts_ns). frame_bgr is HxWx3 uint8 BGR.
        pts_ns may be None.
        """
        return self._store.get()


class GstIrCaptureRawYuy2:
    """
    IR raw capture using:
      v4l2src (do-timestamp=true) -> video/x-raw,format=YUY2 -> appsink

    Returns ndarray shaped (H, W, 2) uint8, i.e. 2 bytes per pixel.
    This matches the "raw-ish" layout your IRCamera.update_frames expects when
    OpenCV CAP_PROP_CONVERT_RGB=0 and you treat the frame as byte pairs.

    For your current IR setup:
      w=256, h=384, fps=25  (two stacked 256x192 halves)
    """

    def __init__(
        self,
        device: str = "/dev/video1",
        w: int = 256,
        h: int = 384,
        fps: int = 25,
        *,
        drop: bool = True,
    ):
        self.w, self.h, self.fps = int(w), int(h), int(fps)
        self.device = device
        self.drop = bool(drop)

        self._store = _LatestFrameStore()

        drop_str = "true" if self.drop else "false"
        maxbuf = 1 if self.drop else 4

        self.pipeline_str = f"""
            v4l2src device={self.device} do-timestamp=true !
            video/x-raw,format=YUY2,width={self.w},height={self.h},framerate={self.fps}/1 !
            appsink name=appsink emit-signals=true drop={drop_str} max-buffers={maxbuf} sync=false
        """

        self.pipeline = Gst.parse_launch(self.pipeline_str)
        self.appsink = self.pipeline.get_by_name("appsink")
        self.appsink.connect("new-sample", self._on_new_sample)
        self._started = False

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        pts = buf.pts
        pts_ns: Optional[int] = None if pts == Gst.CLOCK_TIME_NONE else int(pts)

        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK

        try:
            expected = self.w * self.h * 2  # YUY2 = 16 bpp => 2 bytes/pixel
            data = mapinfo.data
            if len(data) < expected:
                return Gst.FlowReturn.OK

            arr = np.frombuffer(data, dtype=np.uint8, count=expected)
            frame = arr.reshape((self.h, self.w, 2))
            self._store.set(frame, pts_ns)
        finally:
            buf.unmap(mapinfo)

        return Gst.FlowReturn.OK

    def start(self) -> None:
        if self._started:
            return
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self.pipeline.send_event(Gst.Event.new_eos())
        except Exception:
            pass
        self.pipeline.set_state(Gst.State.NULL)
        self._started = False

    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[int]]:
        """
        Returns (frame_raw, pts_ns).
        frame_raw is HxWx2 uint8 representing YUY2 byte pairs.
        pts_ns may be None.
        """
        return self._store.get()



