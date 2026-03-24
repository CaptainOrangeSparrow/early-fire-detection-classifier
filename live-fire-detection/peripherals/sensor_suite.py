# Sensor Package Class
# Use this to get access to sensors


import os
import numpy as np
import time
import cv2
import threading
from dataclasses import dataclass, field
from typing import Optional, List

from peripherals.cameras import Camera, IRCamera
from peripherals.adc import ADC
from peripherals.hdc3022 import HDC3022
from peripherals.uart_sensors import SEN0219, ZE07CO
from peripherals.uart_sensors import CO2Sample as CO2Packet


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
        #adc0_values = adc.read4_once(0)
        #adc1_values = adc.read4_once(1)
        #vals = adc0_values + adc1_values
        adc.update_all()
        vals = adc.get_all_latest()
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

# All sensors Dataclass for ease of access
@dataclass
class Sensors:
    reg_camera: object = None
    ir_camera: object = None
    adc: object = None
    sen0219: object = None
    ze07co: object = None
    hdc3022: object = None

@dataclass
class LatestData:
    reg: LatestFrame = field(default_factory=LatestFrame)
    ir: LatestIRFrame = field(default_factory=LatestIRFrame)
    adc: LatestAdc = field(default_factory=LatestAdc)
    hdc3022: LatestTempHum = field(default_factory=LatestTempHum)
    sen0219: LatestSEN0219 = field(default_factory=LatestSEN0219)
    ze07co: LatestZE07CO = field(default_factory=LatestZE07CO)

@dataclass
class SensorSnapshot:
    t: float
    reg: object
    ir: object
    adc: object
    hdc3022: object
    sen0219: object
    ze07co: object

class SensorSuite:

    def __init__(self, config, stop_evt=None):

        self.config = config
        reg_id = config["reg_id"]
        ir_id = config["ir_id"]
        ir_colormap = config["ir_colormap"]
        ir_norm_settings = config["ir_norm_settings"]
        use_gstreamer = config["use_gstreamer"]
        gst_tee = config["gst_tee"]
        fps = config["fps"]
        self.run_dir = config["run_dir"]

        # Devices
        if stop_evt == None:
            self._stop_evt = threading.Event()
        else:
            self._stop_evt = stop_evt

        # Cameras
        self._reg_cam = Camera(reg_id, use_gstreamer=use_gstreamer, gst_tee=gst_tee, gst_record_path=os.path.join(self.run_dir,"regular.mp4"))
        self._ir_cam = IRCamera(ir_id, ir_colormap, use_gstreamer=use_gstreamer, gst_tee=gst_tee, gst_record_path=os.path.join(self.run_dir, "ir.mp4"), norm_settings=ir_norm_settings)

        # Try to request fps (some cams ignore it)
        if not use_gstreamer:
            for cap in (self._reg_cam._cap, self._ir_cam._cap):
                cap.set(cv2.CAP_PROP_FPS, fps)
        
        # ADC
        self._adc = ADC()
        self._adc.set_adc_channel_names(0, ["MQ-4 (CH4)", "MQ-7 (CO)", "MQ-138 (VOCs)", "KY-026 Flame"])
        self._adc.set_adc_channel_names(1, ["MiCS-6814 NO2", "MiCS-6814 NH3", "MiCS-6814 CO", None])

        # HDC3022
        self._hdc = HDC3022(i2c_bus=self._adc.get_i2c_bus())

        # UART
        self._sen0219 = SEN0219()
        self._ze07co = ZE07CO()

        self._sensors = Sensors(reg_camera=self._reg_cam, ir_camera=self._ir_cam, adc=self._adc, sen0219=self._sen0219, ze07co=self._ze07co, hdc3022=self._hdc)

        # Shared state
        # self.latest_reg = LatestFrame()
        # self.latest_ir  = LatestIRFrame()
        # self.latest_adc = LatestAdc()
        # self.latest_hdc = LatestTempHum()
        # self.latest_sen0219 = LatestSEN0219()
        # self.latest_ze07co = LatestZE07CO()

        # Latest Data Container
        self._latest_data = LatestData()

        # Threads
        self.t_reg = threading.Thread(target=camera_worker, args=(self._reg_cam, self._latest_data.reg, self._stop_evt), daemon=True)
        self.t_ir  = threading.Thread(target=ir_camera_worker, args=(self._ir_cam,  self._latest_data.ir,  self._stop_evt, ir_colormap.name), daemon=True)
        self.t_adc = threading.Thread(target=adc_worker, args=(self._adc, self._latest_data.adc, self._stop_evt), daemon=True)
        self.t_hdc = threading.Thread(target=hdc_worker, args=(self._hdc, self._latest_data.hdc3022, self._stop_evt), daemon=True)
        self.t_sen = threading.Thread(target=sen0219_worker, args=(self._sen0219, self._latest_data.sen0219, self._stop_evt), daemon=True)
        self.t_ze07 = threading.Thread(target=ze07co_worker, args=(self._ze07co, self._latest_data.ze07co, self._stop_evt), daemon=True)

        self.t_reg.start()
        self.t_ir.start()
        self.t_adc.start()
        self.t_hdc.start()
        self.t_sen.start()
        self.t_ze07.start()

    def get_sensor_objects(self):
        return self._sensors

    def get_latest_data(self):
        return self._latest_data

    def get_snapshot(self) -> SensorSnapshot:
        reg_pkt = self._latest_data.reg.get()
        ir_pkt = self._latest_data.ir.get()
        adc_pkt = self._latest_data.adc.get()
        hdc_pkt = self._latest_data.hdc3022.get()
        sen_pkt = self._latest_data.sen0219.get()
        ze_pkt = self._latest_data.ze07co.get()

        return SensorSnapshot(
            t=time.perf_counter(),
            reg=FramePacket(
                t=reg_pkt.t,
                frame=None if reg_pkt.frame is None else reg_pkt.frame.copy()
            ),
            ir=IrFramePacket(
                t=ir_pkt.t,
                frame=None if ir_pkt.frame is None else ir_pkt.frame.copy(),
                tmin=ir_pkt.tmin,
                tmax=ir_pkt.tmax,
                tavg=ir_pkt.tavg,
                tcenter=ir_pkt.tcenter,
                colormap=ir_pkt.colormap,
                sat_above=ir_pkt.sat_above,
                sat_below=ir_pkt.sat_below,
                norm_max=ir_pkt.norm_max,
                norm_min=ir_pkt.norm_min,
                norm_mode=ir_pkt.norm_mode,
            ),
            adc=AdcPacket(
                t=adc_pkt.t,
                values=list(adc_pkt.values),
                sweep_dt=adc_pkt.sweep_dt,
            ),
            hdc3022=TempHumPacket(
                t=hdc_pkt.t,
                temp=hdc_pkt.temp,
                humidity=hdc_pkt.humidity,
            ),
            sen0219=CO2Packet(
                t=sen_pkt.t,
                ppm=sen_pkt.ppm,
                raw_hex=sen_pkt.raw_hex,
                repeated=sen_pkt.repeated,
            ),
            ze07co=CO2Packet(
                t=ze_pkt.t,
                ppm=ze_pkt.ppm,
                raw_hex=ze_pkt.raw_hex,
                repeated=ze_pkt.repeated,
            ),
        )

    def stop_and_close(self):
        if self._stop_evt.is_set():
            return

        self._stop_evt.set()
        
        time.sleep(0.05) # wait for threads to stop, then close cameras

        try:
            self._reg_cam.close()
            self._ir_cam.close()
        except Exception:
            pass

        print("Stop and Closed Sensors")


