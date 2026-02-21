## Authored by Michael Chung

import os
import sys
import csv
import time
import argparse
import threading
from dataclasses import dataclass
from typing import Optional, List

import cv2
import numpy as np
from datetime import datetime as dt
import re
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLineEdit
)

# Custom imports
from peripherals.cameras import Camera, IRCamera
from peripherals.adc import ADC
from peripherals.hdc3022 import HDC3022
from peripherals.uart_sensors import SEN0219, ZE07CO
from peripherals.uart_sensors import CO2Sample as CO2Packet
from utilities.fps_tracker import FPSTracker
from utilities.key_handler import TerminalKeyWatcher, poll_quit_key
from utilities.web_preview import WebPreviewServer, generate_colorbar_png
from utilities.single_instance import SingleInstance
from utilities.ir_raw_writer import IrRawChunkWriter, IRMeta

# ----------------------------
# Thread-safe “latest value” holders
# ----------------------------
@dataclass
class FramePacket:
    t: float
    frame: Optional[np.ndarray]

class LatestFrame:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = FramePacket(t=0.0, frame=None)

    def set(self, frame: np.ndarray, t: float):
        with self._lock:
            self._pkt = FramePacket(t=t, frame=frame)

    def get(self) -> FramePacket:
        with self._lock:
            return self._pkt

@dataclass
class TempHumPacket:
    t: float
    temp: Optional[float] = None
    humidity: Optional[float] = None

class LatestTempHum:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = TempHumPacket(t=0.0, temp=None, humidity=None)
    def set(self, t: float, temp=None, humidity=None):
        with self._lock:
            self._pkt = TempHumPacket(t=t, temp=temp, humidity=humidity)
    def get(self) -> TempHumPacket:
        with self._lock:
            return self._pkt

@dataclass
class IrFramePacket:
    t: float
    frame: Optional[np.ndarray]
    tmin: Optional[float] = None
    tmax: Optional[float] = None
    tavg: Optional[float] = None
    tcenter: Optional[float] = None
    colormap: Optional[str] = None  # e.g. "JET"
    sat_above: Optional[float] = None
    sat_below: Optional[float] = None
    norm_max: Optional[float] = None
    norm_min: Optional[float] = None
    norm_mode: Optional[str] = None

class LatestIRFrame:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = IrFramePacket(t=0.0, frame=None)

    def set(self, frame: np.ndarray, t: float,
            tmin: Optional[float] = None,
            tmax: Optional[float] = None,
            tavg: Optional[float] = None,
            tcenter: Optional[float] = None,
            colormap: Optional[str] = None,
            sat_below: Optional[float] = None,
            sat_above: Optional[float] = None,
            norm_min: Optional[float] = None,
            norm_max: Optional[float] = None,
            norm_mode: Optional[float] = None):
        with self._lock:
            self._pkt = IrFramePacket(
                t=t, frame=frame,
                tmin=tmin, tmax=tmax, tavg=tavg, tcenter=tcenter,
                colormap=colormap,
                sat_above=sat_above, sat_below=sat_below, norm_max=norm_max, norm_min=norm_min,
                norm_mode=norm_mode
            )
    def get(self) -> IrFramePacket:
        with self._lock:
            return self._pkt


@dataclass
class AdcPacket:
    t: float
    values: List[int]   # len 8
    sweep_dt: float

class LatestAdc:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = AdcPacket(t=0.0, values=[-1]*8, sweep_dt=0.0)

    def set(self, pkt: AdcPacket):
        with self._lock:
            self._pkt = pkt

    def get(self) -> AdcPacket:
        with self._lock:
            return self._pkt


# CO2Packet imported from peripherals.uart_sensors
class LatestSEN0219:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = CO2Packet(t=0.0, ppm=0, raw_hex="0x00", repeated=False)
    def set(self, co2_reading: CO2Packet):
        with self._lock:
            self._pkt = co2_reading
    def get(self) -> CO2Packet:
        with self._lock:
            return self._pkt
# CO2Packet is same format for CO ZE07.
class LatestZE07CO:
    def __init__(self):
        self._lock = threading.Lock()
        self._pkt = CO2Packet(t=0.0, ppm=0, raw_hex="0x00", repeated=False)
    def set(self, co_reading: CO2Packet):
        with self._lock:
            self._pkt = co_reading
    def get(self) -> CO2Packet:
        with self._lock:
            return self._pkt


# ----------------------------
# Workers
# ----------------------------
def camera_worker(cam: Camera, latest: LatestFrame, stop_evt: threading.Event):
    while not stop_evt.is_set():
        cam.update_frames()
        f = cam.get_latest_frame()
        if f is not None:
            latest.set(f, time.perf_counter())

def ir_camera_worker(cam: IRCamera, latest: LatestIRFrame, stop_evt: threading.Event, colormap_name: str):
    while not stop_evt.is_set():
        cam.update_frames()
        f = cam.get_latest_frame()
        if f is None:
            continue
        t = time.perf_counter()
        tmin, tmax, tavg, tcenter = cam.get_temp_stats()  # this method to IRCamera
        norm_min, norm_max, sat_below, sat_above = cam.get_fixed_norm_stats()
        latest.set(
            frame=f,
            t=t,
            tmin=tmin,
            tmax=tmax,
            tavg=tavg,
            tcenter=tcenter,
            colormap=colormap_name,
            sat_below=sat_below,
            sat_above=sat_above,
            norm_min=norm_min,
            norm_max=norm_max,
            norm_mode=cam.get_norm_mode().value
        )

def adc_worker(adc: ADC, latest: LatestAdc, stop_evt: threading.Event):
    while not stop_evt.is_set():
        t0 = time.perf_counter()
        # vals = []
        # for dev in (0, 1):
        #     for ch in (0, 1, 2, 3):
        #         vals.append(adc.read(dev, ch))
        adc0_values = adc.read4_once(0)
        adc1_values = adc.read4_once(1)
        vals = adc0_values + adc1_values
        t1 = time.perf_counter()
        latest.set(AdcPacket(t=t1, values=vals, sweep_dt=(t1 - t0)))

def hdc_worker(hdc: HDC3022, latest: LatestTempHum, stop_evt: threading.Event):
    while not stop_evt.is_set():
        temp, hum = hdc.read_temp_rh()
        latest.set(t=time.perf_counter(), temp=temp, humidity=hum)
def sen0219_worker(sen0219: SEN0219, latest: LatestSEN0219, stop_evt: threading.Event):
    while not stop_evt.is_set():
        latest.set(co2_reading=sen0219.read_sample())
def ze07co_worker(ze07co: ZE07CO, latest: LatestZE07CO, stop_evt: threading.Event):
    while not stop_evt.is_set():
        latest.set(co_reading=ze07co.read_sample())
        


# ----------------------------
# Helpers
# ----------------------------
def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)

def make_unique_dir(parent: str, name: str, fps: float) -> str:
    """
    Create recordings/<name> or recordings/<name>_001, _002, ...
    Returns the final path.
    """
    os.makedirs(parent, exist_ok=True)

    now = dt.now()
    date_str = now.strftime("%Y-%m-%d")
    hms_str  = now.strftime("%H-%M-%S")
    unix_ts  = int(time.time())

    # IMPORTANT: keep fps formatting stable across runs
    fps_str = f"{int(round(fps))}fps"

    base = f"recording_{name}_{fps_str}_{date_str}"
    prefix = base + "_"

    max_idx = 0
    for d in os.listdir(parent):
        if not d.startswith(prefix):
            continue

        # d looks like: base_<index>_...
        rest = d[len(prefix):]            # "<index>_..."
        idx_str = rest.split("_", 1)[0]   # "<index>"

        if idx_str.isdigit():
            max_idx = max(max_idx, int(idx_str))

    next_idx = max_idx + 1

    run_name = f"{base}_{next_idx:03d}_{unix_ts}_{hms_str}"
    full = os.path.join(parent, run_name)
    os.makedirs(full, exist_ok=False)
    return full

    raise RuntimeError("Could not create a unique recordings directory.")

def write_meta_json(meta_path, meta_obj, overwrite_meta=False):
    if overwrite_meta or (not os.path.exists(meta_path)):
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_obj, f, indent=2)
    else:
        raise RuntimeError("Could not Write Meta File. Path already exists: " + meta_path)

# ----------------------------
# Main GUI
# ----------------------------
class RecorderGUI(QWidget):
    def __init__(
        self,
        run_dir: str,
        reg_id: int,
        ir_id: int,
        fps: float,
        ir_colormap: IRCamera.ColorMap,
        ir_norm_settings: tuple,
        backend: Optional[int] = None,
        show: bool = True,
        console_status: bool = False,
        terminal_quit: bool = False,
        view_only: bool = False,
        web_preview: bool = False,
        use_gstreamer: bool = False,
        verbose: bool = False
    ):
        super().__init__()
        self.setWindowTitle("Dual Camera + ADC Recorder (press 'q' to stop)")
        self.run_dir = run_dir
        self.fps = fps
        self.console_status = console_status
        self.terminal_quit = terminal_quit
        self.view_only = view_only

        # Devices
        self.stop_evt = threading.Event()
        
        # Cameras
        self.reg_cam = Camera(reg_id, use_gstreamer=use_gstreamer)
        self.ir_cam = IRCamera(ir_id, ir_colormap, use_gstreamer=use_gstreamer, norm_settings=ir_norm_settings)

        # ADC
        self.adc = ADC()
        self.adc.set_adc_channel_names(0, ["MQ-4 (CH4)", "MQ-7 (CO)", "MQ-138 (VOCs)", "KY-026 Flame"])
        self.adc.set_adc_channel_names(1, ["MiCS-6814 NO2", "MiCS-6814 NH3", "MiCS-6814 CO", None])

        # HDC3022
        self.hdc = HDC3022(i2c_bus=self.adc.get_i2c_bus())

        # UART
        self.sen0219 = SEN0219()
        self.ze07co = ZE07CO()

        # Try to request fps (some cams ignore it)
        for cap in (self.reg_cam._cap, self.ir_cam._cap):
            cap.set(cv2.CAP_PROP_FPS, fps)

        # Shared state
        self.latest_reg = LatestFrame()
        self.latest_ir  = LatestIRFrame()
        self.latest_adc = LatestAdc()
        self.latest_hdc = LatestTempHum()
        self.latest_sen0219 = LatestSEN0219()
        self.latest_ze07co = LatestZE07CO()

        # Threads
        self.t_reg = threading.Thread(target=camera_worker, args=(self.reg_cam, self.latest_reg, self.stop_evt), daemon=True)
        self.t_ir  = threading.Thread(target=ir_camera_worker, args=(self.ir_cam,  self.latest_ir,  self.stop_evt, ir_colormap.name), daemon=True)
        self.t_adc = threading.Thread(target=adc_worker, args=(self.adc, self.latest_adc, self.stop_evt), daemon=True)
        self.t_hdc = threading.Thread(target=hdc_worker, args=(self.hdc, self.latest_hdc, self.stop_evt), daemon=True)
        self.t_sen = threading.Thread(target=sen0219_worker, args=(self.sen0219, self.latest_sen0219, self.stop_evt), daemon=True)
        self.t_ze07 = threading.Thread(target=ze07co_worker, args=(self.ze07co, self.latest_ze07co, self.stop_evt), daemon=True)

        self.t_reg.start()
        self.t_ir.start()
        self.t_adc.start()
        self.t_hdc.start()
        self.t_sen.start()
        self.t_ze07.start()

        # UI
        self.reg_label = QLabel("Regular camera")
        self.ir_label  = QLabel("IR camera")
        self.reg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ir_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        adc_group = QGroupBox("ADC (raw)")
        adc_grid = QGridLayout()
        self.adc_fields = []
        names = [
            "ADC0 CH0", "ADC0 CH1", "ADC0 CH2", "ADC0 CH3",
            "ADC1 CH0", "ADC1 CH1", "ADC1 CH2", "ADC1 CH3",
        ]
        for i, name in enumerate(names):
            lab = QLabel(name)
            val = QLabel("-")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.adc_fields.append(val)
            adc_grid.addWidget(lab, i, 0)
            adc_grid.addWidget(val, i, 1)
        adc_group.setLayout(adc_grid)

        video_row = QHBoxLayout()
        video_row.addWidget(self.reg_label, 1)
        video_row.addWidget(self.ir_label, 1)

        right_col = QVBoxLayout()
        right_col.addWidget(adc_group)
        right_col.addWidget(QLabel("Status"))
        right_col.addWidget(self.status)

        main = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addLayout(video_row)
        main.addLayout(left_col, 3)
        main.addLayout(right_col, 1)
        self.setLayout(main)

        # Writers and CSV
        self.writer_reg = None
        self.writer_ir = None

        if not self.view_only:
            self.csv_path = os.path.join(self.run_dir, "adc.csv")
            self.csv_f = open(self.csv_path, "w", newline="")
            self.csv_w = csv.writer(self.csv_f)
            self.csv_w.writerow([
                "frame_idx",
                "t_sample_perf_counter",
                "t_reg_frame",
                "t_ir_frame",
                "t_adc_sweep",
                "adc_sweep_dt_s",
                "adc0_ch0","adc0_ch1","adc0_ch2","adc0_ch3",
                "adc1_ch0","adc1_ch1","adc1_ch2","adc1_ch3",
                "ir_min", "ir_max", "ir_avg", "ir_center",
                "t_hdc_sample", "hdc_temp", "hdc_humidity",
                "t_sen0219_sample", "co2_ppm",
                "t_ze07co_sample", "co_ppm",
            ])

        # IR Writer. Still create for metadata even if view only
        self.ir_raw_writer = IrRawChunkWriter(
            recording_dir=self.run_dir,
            meta=IRMeta(
                fps_target=self.fps,         # e.g. 25
                colormap=ir_colormap.name,     # "JET", "INFERNO", etc.
                display_scale=2.5,
                chunk_frames=250,                   # 10 seconds @ 25 fps
            ),
        )

        self.frame_idx = 0
        self.t0 = time.perf_counter()

        # Device meta info
        meta_info = {
            "data_recorder": {
                "params": {
                    "run_dir": run_dir,
                    "rgb_dev_id": reg_id,
                    "ir_dev_id": ir_id,
                    "fps": fps,
                    "ir_colormap": ir_colormap.name,
                    "backend": backend,
                    "show": show,
                    "console_status": console_status,
                    "terminal_quit": terminal_quit,
                    "view_only": view_only,
                    "web_preview": web_preview,
                    "use_gstreamer": use_gstreamer,
                    "verbose": verbose,
                },
                "output_info": {
                    "video_formats": "[mp4]",
                    "tabular_formats": "[csv, npz]",
                    "other_file_formats": "[json]",
                    "recording_target_fps": 25,
                    "creation_unix_time": time.time(),
                    "perf_counter_time_start": self.t0,
                },
            },
            "cameras": {
                "rgb": self.reg_cam.get_meta_info(),
                "thermal": self.ir_cam.get_meta_info(),
            },
            "adc": self.adc.get_meta_info(),
            "ir_raw_writer": self.ir_raw_writer.get_meta_info(),
            "temp_and_humidity": self.hdc.get_meta_info(),
            "uart": {
                "sen0219": self.sen0219.get_meta_info(),
                "ze07-co": self.ze07co.get_meta_info(),
            },
        }
        # Write meta json file
        if not self.view_only:
            write_meta_json(os.path.join(self.run_dir, "meta.json"), meta_info)


        # Flask App
        self.web = None
        self._last_status_string = "Starting Web App..."
        if web_preview:
            self.web = WebPreviewServer(
                meta_info=meta_info,
                get_rgb_frame=lambda: self.latest_reg.get().frame,
                get_ir_frame=lambda: self.latest_ir.get().frame,
                get_status=lambda: self._last_status_string,
                get_adc_values=lambda: self.latest_adc.get().values,
                get_ir_stats=lambda: (
                    self.latest_ir.get().tmin,
                    self.latest_ir.get().tmax,
                    self.latest_ir.get().tavg,
                    self.latest_ir.get().tcenter),
                get_cmap=lambda: self.latest_ir.get().colormap,
                get_ir_norm_stats=lambda: (
                    self.latest_ir.get().norm_min,
                    self.latest_ir.get().norm_max,
                    self.latest_ir.get().sat_below,
                    self.latest_ir.get().sat_above,
                    self.latest_ir.get().norm_mode),
                get_hdc_data=lambda: (
                    self.latest_hdc.get().temp,
                    self.latest_hdc.get().humidity),
                get_carbon_data=lambda: (
                    self.latest_sen0219.get().ppm,
                    self.latest_ze07co.get().ppm),
                verbose=verbose
            )
            self.web.start()

        # FPS tracking
        self.fps_tracker = FPSTracker(window_s=1.0)

        # Timer at fps
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(int(1000 / fps))
        
        self.kb_timer = QTimer(self)
        self.kb_timer.timeout.connect(self._check_terminal_key)
        self.kb_timer.start(30)  # ~33 Hz

        if self.view_only:
            self.status.setText("View only. NOT Recording!")
        else:
            self.status.setText(f"Recording to {self.run_dir}")

        if not show:
            self.hide()

    def _check_terminal_key(self):
        if self.terminal_quit and poll_quit_key():
            print("\nQuitting...")
            if not self.view_only:
                print("Saving Data and Recordings...\n")
            else:
                print()
            self.stop_and_close()

    def _init_writers_if_ready(self):
        reg = self.latest_reg.get().frame
        ir  = self.latest_ir.get().frame
        if reg is None or ir is None:
            return False

        h0, w0 = reg.shape[:2]
        h1, w1 = ir.shape[:2]

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer_reg = cv2.VideoWriter(os.path.join(self.run_dir, "regular.mp4"), fourcc, self.fps, (w0, h0))
        self.writer_ir  = cv2.VideoWriter(os.path.join(self.run_dir, "ir.mp4"),      fourcc, self.fps, (w1, h1))
        return True

    def on_tick(self):
        if not self.view_only:
            if self.writer_reg is None or self.writer_ir is None:
                if not self._init_writers_if_ready():
                    return

        pkt_reg = self.latest_reg.get()
        pkt_ir  = self.latest_ir.get()
        pkt_adc = self.latest_adc.get()
        pkt_hdc = self.latest_hdc.get()
        pkt_sen = self.latest_sen0219.get()
        pkt_ze07 = self.latest_ze07co.get()

        # UI updates
        if pkt_reg.frame is not None:
            qimg = bgr_to_qimage(pkt_reg.frame)
            self.reg_label.setPixmap(QPixmap.fromImage(qimg).scaled(
                self.reg_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
        if pkt_ir.frame is not None:
            qimg = bgr_to_qimage(pkt_ir.frame)
            self.ir_label.setPixmap(QPixmap.fromImage(qimg).scaled(
                self.ir_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))

        for i, v in enumerate(pkt_adc.values):
            self.adc_fields[i].setText(str(v))

        # Write synchronized sample
        if pkt_reg.frame is None or pkt_ir.frame is None:
            return

        t_sample = time.perf_counter()

        if not self.view_only:
            self.writer_reg.write(pkt_reg.frame)
            self.writer_ir.write(pkt_ir.frame)
            
            # ---- Store raw thermal frame (uint16, 192x256) in NPZ chunks ----
            raw16 = self.ir_cam.get_raw_thermal_frame()
            if raw16 is not None:
                self.ir_raw_writer.append(self.frame_idx, t_sample, raw16)

            self.csv_w.writerow([
                self.frame_idx,
                f"{t_sample:.9f}",
                f"{pkt_reg.t:.9f}",
                f"{pkt_ir.t:.9f}",
                f"{pkt_adc.t:.9f}",
                f"{pkt_adc.sweep_dt:.6f}",
                *pkt_adc.values,
                pkt_ir.tmin, pkt_ir.tmax, pkt_ir.tavg, pkt_ir.tcenter,
                f"{pkt_hdc.t:.9f}",
                pkt_hdc.temp, pkt_hdc.humidity,
                f"{pkt_sen.t:.9f}",
                pkt_sen.ppm,
                f"{pkt_ze07.t:.9f}",
                pkt_ze07.ppm,
            ])
        
        self.fps_tracker.tick()
        elapsed = t_sample - self.t0
        skew_ms = abs(pkt_reg.t - pkt_ir.t) * 1000.0
        current_fps = self.fps_tracker.get_fps()
        destination_text = "Preview only. NOT Recording!" if self.view_only else f"Recording to {self.run_dir}"
        fps_text = "view_only_fps" if self.view_only else "write_fps"
        status_str = (
            f"{destination_text}\n\nframes={self.frame_idx}\n"
            f"time_elapsed={elapsed:.1f}s\n"
            f"{fps_text}≈{current_fps:.2f}\n"
            f"rgb-ir_skew≈{skew_ms:.1f}ms\n"
            f"adc_sweep_dt≈{pkt_adc.sweep_dt*1000:.1f}ms\n"
        )
        self.status.setText(status_str)
        self._last_status_string = status_str

        if self.console_status:
            print("\r" + status_str.replace("\n", "  ").ljust(120).split("  ", 1)[1] + f"ADC={pkt_adc.values}", end="", flush=True)

        self.frame_idx += 1

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Q:
            self.stop_and_close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_and_close()
        event.accept()

    def stop_and_close(self):
        if self.stop_evt.is_set():
            return

        self.stop_evt.set()
        self.timer.stop()

        if hasattr(self, "ir_raw_writer") and self.ir_raw_writer is not None:
            self.ir_raw_writer.close()

        try:
            if self.writer_reg is not None:
                self.writer_reg.release()
            if self.writer_ir is not None:
                self.writer_ir.release()
        except Exception:
            pass

        try:
            if self.csv_f is not None:
                self.csv_f.flush()
                self.csv_f.close()
        except Exception:
            pass

        try:
            self.reg_cam.close()
            self.ir_cam.close()
        except Exception:
            pass

        self.status.setText(f"Stopped. Saved to: {self.run_dir}")
        QApplication.quit()


def parse_args():
    p = argparse.ArgumentParser(description="Record regular + IR video and ADS1115 data.")
    p.add_argument("name", help="Run folder name (created inside ./recordings/)")
    p.add_argument("--recordings-dir", default="saved_recordings", help="Parent directory for all runs (default: saved_recordings)")
    p.add_argument("--camera-id", type=int, default=0, help="Regular camera device id (default: 0)")
    p.add_argument("--infrared-camera-id",  type=int, default=2, help="IR camera device id (default: 2)")
    p.add_argument("--fps", type=float, default=25.0, help="Target fps for saving + UI tick (default: 25)")
    p.add_argument("--ir-colormap", default="INFERNO",
                   choices=[c.name for c in IRCamera.ColorMap],
                   help="IR colormap (default: INFERNO)")
    p.add_argument("--no-gui", action="store_true", help="Run headless (still stops on q if focused window exists)")
    p.add_argument("--console-status", action="store_true", help="Also print status + ADC values live to console")
    p.add_argument("--view-only", action="store_true", help="Show streams + ADC but do not write any recordings")
    p.add_argument("--web-stream", action="store_true", help="Serve a browser web stream (MJPEG + JSON) at http://localhost:5000/")
    p.add_argument("--gstreamer", action="store_true", help="Use GStreamer pipelines for camera capture (cv2.CAP_GSTREAMER)")
    p.add_argument("-v", "--verbose", action="store_true", help="Print out detailed logging. (For web preview)")
    p.add_argument("--ir-norm", type=str, default="minmax", help="Set the normalization method for IR camera frames. (minmax or fixed)")
    p.add_argument("--ir-max", type=float, default="80.0", help="Set the maximum temperature for the IR camera in fixed normalization mode")
    p.add_argument("--ir-min", type=float, default="10.0", help="Set the minimum temperature for the IR camera in fixed normalization mode")

    return p.parse_args()


def main():
    args = parse_args()

    # Only allow one instance of this to run
    lock = SingleInstance("/tmp/jetson_data-recording-script.lock")
    try:
        lock.acquire()
    except RuntimeError as e:
        print()
        print(str(e))
        print("Another instance of this script is already running!\n")
        raise SystemExit(1)

    run_dir = None if args.view_only else make_unique_dir(args.recordings_dir, args.name, args.fps)
    cmap = IRCamera.ColorMap[args.ir_colormap]
    generate_colorbar_png(os.path.join("utilities/static", "colorbar.png"), IRCamera.COLORMAPS_LIST[cmap.value], num_ticks=3)

    print()
    if args.view_only:
        print("View Only Mode Started. (NOT RECORDING!). Press 'q' to stop the preview\n")
    else:
        print("Saving to:", run_dir)
        print("Recording started. Press 'q' to stop the recording and save\n")
    
    ir_norm_settings = (args.ir_norm, args.ir_max, args.ir_min)
    app = QApplication(sys.argv)
    w = RecorderGUI(
        run_dir=run_dir,
        reg_id=args.camera_id,
        ir_id=args.infrared_camera_id,
        fps=args.fps,
        ir_colormap=cmap,
        ir_norm_settings = ir_norm_settings,
        show=(not args.no_gui),
        console_status=args.console_status,
        terminal_quit = True,
        view_only = args.view_only,
        web_preview = args.web_stream,
        use_gstreamer = args.gstreamer,
        verbose = args.verbose
    )
    w.resize(1400, 700)
    if not args.no_gui:
        w.show()

    with TerminalKeyWatcher():
        sys.exit(app.exec())

    print("Done\n")

if __name__ == "__main__":
    main()

