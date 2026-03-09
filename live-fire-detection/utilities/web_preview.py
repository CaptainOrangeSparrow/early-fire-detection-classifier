## Authored by Michael Chung

from __future__ import annotations
import time
import threading
from typing import Callable, List, Optional

import os
import cv2
import numpy as np
import json
from flask import Flask, Response, jsonify, send_from_directory
import logging

from utilities.fps_tracker import FPSTracker

WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
WEB_JPEG_QUALITY = 70
WEB_PREVIEW_WIDTH = 960
WEB_PREVIEW_FPS = 25.0
WEB_FPS_WINDOW_S = 1.0

def _safe_resize(img: np.ndarray, width: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w == 0:
        return img
    scale = width / float(w)
    new_h = int(round(h * scale))
    return cv2.resize(img, (width, new_h), interpolation=cv2.INTER_AREA)

def _hconcat_letterbox(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Concatenate side-by-side while matching heights by letterboxing the smaller one.
    """
    ha, wa = a.shape[:2]
    hb, wb = b.shape[:2]
    H = max(ha, hb)

    def pad_to_h(img, H):
        h, w = img.shape[:2]
        if h == H:
            return img
        top = (H - h) // 2
        bot = H - h - top
        return cv2.copyMakeBorder(img, top, bot, 0, 0, borderType=cv2.BORDER_CONSTANT, value=(0,0,0))

    a2 = pad_to_h(a, H)
    b2 = pad_to_h(b, H)
    return cv2.hconcat([a2, b2])

'''
def generate_colorbar_png(path: str, cv2_colormap: int, width: int = 512, height: int = 8):
    ramp = np.arange(256, dtype=np.uint8).reshape(1, 256)      # 1x256
    bar = cv2.applyColorMap(ramp, cv2_colormap)                # (1,256,3) BGR
    bar = cv2.resize(bar, (width, height), interpolation=cv2.INTER_NEAREST)
    ok, png = cv2.imencode(".png", bar)
    if not ok:
        raise RuntimeError("Failed to encode colorbar PNG")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png.tobytes())
'''

def generate_colorbar_png(path: str, cv2_colormap: int,
                          width: int = 512, height: int = 8,
                          num_ticks: int = 0,
                          tick_color=(255, 255, 255), tick_thickness: int = 1):
    ramp = np.arange(256, dtype=np.uint8).reshape(1, 256)      # 1x256
    bar = cv2.applyColorMap(ramp, cv2_colormap)                # (1,256,3) BGR
    bar = cv2.resize(bar, (width, height), interpolation=cv2.INTER_NEAREST)

    # Draw equally spaced vertical tick marks
    if num_ticks > 0:
        for i in range(num_ticks):
            x = int((i + 1) * width / (num_ticks + 1))
            cv2.line(bar, (x, 0), (x, height-1), tick_color, tick_thickness)

    ok, png = cv2.imencode(".png", bar)
    if not ok:
        raise RuntimeError("Failed to encode colorbar PNG")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png.tobytes())


class WebPreviewServer:
    """
    Flask MJPEG + JSON status server.
    Pass callables that return latest frames and status.
    """
    def __init__(
        self,
        meta_info,
        get_rgb_frame: Callable[[], Optional[np.ndarray]],
        get_ir_frame: Callable[[], Optional[np.ndarray]],
        get_status: Callable[[], str],
        get_adc_values: Callable[[], List[int]],
        get_ir_stats: Callable[[], tuple],
        get_cmap: Callable[[], str],
        get_ir_norm_stats: Callable[[], tuple],
        get_hdc_data: Callable[[], tuple],
        get_carbon_data: Callable[[], tuple],
        verbose=False
    ):
        self._meta_info = meta_info
        self.get_rgb_frame = get_rgb_frame
        self.get_ir_frame = get_ir_frame
        self.get_status = get_status
        self.get_adc_values = get_adc_values
        self.get_ir_stats = get_ir_stats
        self.get_cmap = get_cmap
        self.get_ir_norm_stats = get_ir_norm_stats
        self.get_hdc_data = get_hdc_data
        self.get_carbon_data = get_carbon_data
        self.verbose = verbose

        self.runstart = self._meta_info["data_recorder"]["output_info"]["creation_unix_time"]

        self.host = WEB_HOST
        self.port = WEB_PORT
        self.jpeg_quality = int(WEB_JPEG_QUALITY)
        self.preview_width = int(WEB_PREVIEW_WIDTH)
        self.preview_fps = float(WEB_PREVIEW_FPS)

        self._stop_evt = threading.Event()
        self._state_lock = threading.Lock()
        self._latest_jpeg = None   # type: bytes | None
        self._web_fps_est = 0.0
        self._producer_thread = None

        self._fpstracker = FPSTracker()
        self._current_web_fps = 0.0

        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.app = Flask(__name__)
        self._routes()

        print(f"Web preview: http://{WEB_HOST}:{WEB_PORT}/\n")

    def _producer_loop(self):
        period = 1.0 / max(self.preview_fps, 1)

        while not self._stop_evt.is_set():
            t0 = time.perf_counter()

            rgb = self.get_rgb_frame()
            ir  = self.get_ir_frame()

            if rgb is not None and ir is not None:
                # IMPORTANT: copy so capture threads can't mutate while encoding
                rgb = rgb.copy()
                ir  = ir.copy()

                rgb_small = _safe_resize(rgb, self.preview_width)
                ir_small  = _safe_resize(ir,  self.preview_width)
                combo = _hconcat_letterbox(rgb_small, ir_small)

                ok, jpg = cv2.imencode(
                    ".jpg",
                    combo,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)]
                )
                if ok:
                    self._fpstracker.tick()
                    #with self._state_lock:
                    self._latest_jpeg = jpg.tobytes()
                    self._current_web_fps = self._fpstracker.get_fps()

            dt = time.perf_counter() - t0
            sleep_s = period - dt
            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                time.sleep(0.001)

    def _routes(self):
        @self.app.route("/")
        def index():
            return send_from_directory("static", "index.html")

        @self.app.route("/video")
        def video():
            return Response(self._mjpeg_gen(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")
        
        @self.app.route("/events")
        def events():
            period = 1.0 / max(self.preview_fps, 1)
            def gen():
                # Push at same cadence as your web producer, or separate constant
                #period = 1.0 / 10  # 10 Hz
                while not self._stop_evt.is_set():
                    #with self._state_lock:
                    web_fps = float(self._current_web_fps)
                    ir_min, ir_max, ir_avg, ir_center = self.get_ir_stats()
                    norm_min, norm_max, sat_below, sat_above, norm_mode = self.get_ir_norm_stats()
                    temp, hum = self.get_hdc_data()
                    co2_ppm, co_ppm = self.get_carbon_data()
                    payload = {
                        "t": time.time(),
                        "status": self.get_status(),
                        "adc": self.get_adc_values(),
                        "web_fps": web_fps,
                        "ir_min": ir_min,
                        "ir_max": ir_max,
                        "cmap": self.get_cmap(),
                        "norm_mode": norm_mode,
                        "norm_max": norm_max,
                        "norm_min": norm_min,
                        "sat_above": sat_above,
                        "sat_below": sat_below,
                        "runstart": self.runstart,
                        "hdc_temp_c": temp,
                        "hdc_humidity_rh": hum,
                        "co2_ppm": co2_ppm,
                        "co_ppm": co_ppm,
                    }
                    # SSE format: "data: <json>\n\n"
                    yield f"data: {json.dumps(payload)}\n\n"
                    time.sleep(period)

            return Response(gen(), mimetype="text/event-stream")
        
        @self.app.route("/meta")
        def meta():
            return jsonify(self._meta_info)

    def _mjpeg_gen(self):
        while not self._stop_evt.is_set():
            #with self._state_lock:
            jpg = self._latest_jpeg
            if jpg is None:
                time.sleep(0.001)
                continue
            yield (b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")

            # small sleep so we don't busy-spin if the client is fast
            time.sleep(0.001)

    def start(self):
        if self._thread is not None:
            return
        
        def run():

            # restrict werkzeug log messages
            if not self.verbose:
                logging.getLogger("werkzeug").setLevel(logging.ERROR)

            # threaded=True lets Flask handle multiple requests (video + json) easily
            self.app.run(host=self.host, port=self.port, threaded=True, debug=False, use_reloader=False)

        self._thread = threading.Thread(target=run, daemon=True)
        
        # start producer
        if self._producer_thread is None:
            self._producer_thread = threading.Thread(target=self._producer_loop, daemon=True)
            self._producer_thread.start()

        # start flask thread
        self._thread.start()
        print("\nUSE The Q KEY TO QUIT!\n")

    def stop(self):
        self._stop_evt.set()
        # Flask dev server doesn't have a clean stop hook; daemon thread exits when process exits.

