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

# Custom imports
from peripherals.cameras import Camera, IRCamera
from peripherals.adc import ADC
from peripherals.hdc3022 import HDC3022
from peripherals.uart_sensors import SEN0219, ZE07CO
from peripherals.uart_sensors import CO2Sample as CO2Packet
from peripherals.sensor_suite import SensorSuite
from utilities.fps_tracker import FPSTracker
from utilities.key_handler import TerminalKeyWatcher, poll_quit_key
from utilities.web_preview import WebPreviewServer, generate_colorbar_png
from utilities.single_instance import SingleInstance
#from utilities.ir_raw_writer import IrRawChunkWriter, IRMeta
from utilities.ir_raw_writer_buffered import IRMeta
from utilities.ir_raw_writer_buffered import IrRawChunkWriterDoubleBuffer as IrRawChunkWriter


# ----------------------------
# Helpers
# ----------------------------
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
class DataRecorder:
    def __init__(
        self,
        run_dir: str,
        reg_id: int,
        ir_id: int,
        fps: int,
        ir_colormap: IRCamera.ColorMap,
        ir_norm_settings: tuple,
        sensorsuite: SensorSuite,
        backend: Optional[int] = None,
        console_status: bool = False,
        terminal_quit: bool = True,
        view_only: bool = False,
        use_gstreamer: bool = False,
        verbose: bool = False
    ):
        
        print()
        if view_only:
            print("View Only Mode Started. (NOT RECORDING!). Press 'q' to stop the preview\n")
        else:
            print("Saving to:", run_dir)
            print("Recording started. Press 'q' to stop the recording and save\n")

        self.run_dir = run_dir
        self.fps = fps
        self.console_status = console_status
        self.terminal_quit = terminal_quit
        self.view_only = view_only

        self.use_gstreamer = use_gstreamer
        self.gst_tee = False

        # Devices
        self.stop_evt = threading.Event()
        
        self.sensorsuite = sensorsuite

        self.sensors = self.sensorsuite.get_sensor_objects()
        self.reg_cam = self.sensors.reg_camera
        self.ir_cam = self.sensors.ir_camera
        self.adc = self.sensors.adc
        self.sen0219 = self.sensors.sen0219
        self.ze07co = self.sensors.ze07co
        self.hdc = self.sensors.hdc3022

        names = [
            "ADC0 CH0", "ADC0 CH1", "ADC0 CH2", "ADC0 CH3",
            "ADC1 CH0", "ADC1 CH1", "ADC1 CH2", "ADC1 CH3",
        ]
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
                    "console_status": console_status,
                    "terminal_quit": terminal_quit,
                    "view_only": view_only,
                    "web_preview": True,
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

        # ML results
        self.ml_results = None

        # Flask App
        #self.updated_sensors = None
        self.web = None
        self._last_status_string = "Starting Web App..."
        self.web = WebPreviewServer(
            meta_info=meta_info,
            get_status=lambda: self._last_status_string,
            get_latest_sensor_data=lambda: self.sensorsuite.get_latest_data(),
            #get_latest_sensor_data=lambda: self.updated_sensors,
            verbose=verbose
        )
        self.web.start()

        # FPS tracking
        self.fps_tracker = FPSTracker(window_s=1.0)

    #def _check_terminal_key(self):
    #    if self.terminal_quit and poll_quit_key():
    #        print("\nQuitting...")
    #        if not self.view_only:
    #            print("Saving Data and Recordings...\n")
    #        else:
    #            print()
    #        self.stop_and_close()

    def get_web_app(self):
        return self.web

    def _init_writers_if_ready(self):
        reg = self.sensorsuite.get_latest_data().reg.get().frame
        ir  = self.sensorsuite.get_latest_data().ir.get().frame
        if reg is None or ir is None:
            return False

        h0, w0 = reg.shape[:2]
        h1, w1 = ir.shape[:2]

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        rgb_written_by_gst = bool(self.use_gstreamer and not self.gst_tee)

        # TODO gate gst_tee
        self.writer_reg = cv2.VideoWriter(os.path.join(self.run_dir, "regular.mp4"), fourcc, self.fps, (w0, h0))
        self.writer_ir  = cv2.VideoWriter(os.path.join(self.run_dir, "ir.mp4"),      fourcc, self.fps, (w1, h1))
        return True

    def on_tick(self, snapshot=None, ml_results=None):
        if not self.view_only:
            if self.writer_reg is None or self.writer_ir is None:
                if not self._init_writers_if_ready():
                    return
        
        #self.updated_sensors = snapshot

        # Update ML
        self.ml_results = ml_results

        if snapshot == None:
            snapshot = self.sensorsuite.get_snapshot()
        pkt_reg = snapshot.reg
        pkt_ir  = snapshot.ir
        pkt_adc = snapshot.adc
        pkt_hdc = snapshot.hdc3022
        pkt_sen = snapshot.sen0219
        pkt_ze07 = snapshot.ze07co

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
        self._last_status_string = status_str

        if self.console_status:
            print("\r" + status_str.replace("\n", "  ").ljust(120).split("  ", 1)[1] + f"ADC={pkt_adc.values}", end="", flush=True)

        self.frame_idx += 1

    def stop_and_close(self):
        if self.stop_evt.is_set():
            return

        self.stop_evt.set()

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

        self.web.stop()

        print(f"Stopped. Saved to: {self.run_dir}")


