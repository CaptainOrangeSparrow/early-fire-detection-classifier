'''
Author: Michael Chung
Date: November 20, 2025
ECE 364D
'''

import os
import cv2
import numpy as np
from enum import Enum

class Camera():

    def __init__(self, device_id, use_gstreamer=False, gst_tee=False, gst_pipeline=None, gst_record_path=None, width=640, height=480, fps=30, video_format="MJPG"):

        self._current_frame = None
        self._device_id = device_id
        self._use_gstreamer = use_gstreamer
        self._gst_pipeline = gst_pipeline
        self._video_format = video_format

        self._backend = None
        self._cap = None
        self._gst = None
        self._gst_last_pts_ns = None

        if use_gstreamer:
            '''
            if gst_pipeline is None:
                print("Using Default-Custom-Defined Gstreamer Pipeline...")
                #gst_pipeline = self.gst_pipeline(self._device_id, 1280, 720, 30) #1MP, 720p
                gst_pipeline = self.gst_pipeline(self._device_id, 640, 480, 30)
            #self._cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            '''
            # We will not use cv2 for gstreamer, as the current cv2 build does not support gstreamer. Instead we will use gi.
            
            self._gst = self._build_gst_backend(
                device_id=device_id,
                gst_tee=gst_tee,
                gst_record_path=gst_record_path,
                gst_bitrate = int(8000000),
                width=width,
                height=height,
                fps=fps,
            )
            self._gst.start()
            self._backend = "gst_gi"

        else:
            self._cap = cv2.VideoCapture(device_id, cv2.CAP_V4L2)
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*video_format))
            self._backend = "opencv_v4l2"

            if not self._cap.isOpened():
                #print("Gstreamer pipeline:", gst_pipeline)
                raise RuntimeError("Error: Could not open camera device=" + str(self._device_id))

    def _build_gst_backend(self, *, device_id, gst_tee, gst_record_path, gst_bitrate, width, height, fps):
        """
        Virtual hook: subclasses override to provide the right GStreamer capture backend.
        Base class default: RGB MJPG -> nvjpegdec -> appsink, optional tee-record.
        """
        dev = f"/dev/video{device_id}" if isinstance(device_id, int) else str(device_id)
        if gst_tee and not gst_record_path:
            raise ValueError("gst_tee=True requires gst_record_path")
        return GstRgbCapture(
            device=dev, w=width, h=height, fps=fps,
            tee=bool(gst_tee),
            out_mp4=gst_record_path if gst_tee else None,
            bitrate=int(gst_bitrate),
        )

    def is_opened(self):
        if self._backend == "gst_gi":
            return self._gst is not None
        return self._cap is not None and self._cap.isOpened()

    def get_latest_frame(self):
        return self._current_frame

    def get_latest_pts_ns(self):
        """Optional convenience for sync/debugging."""
        return self._gst_last_pts_ns

    def update_frames(self):
        # GStreamer
        if self._backend == "gst_gi":
            frame, pts_ns = self._gst.get_latest()
            if frame is not None:
                self._gst_last_pts_ns = pts_ns
            else:
                #print("Error rgb gst_gi frame is None")
                return
        else:
            # OpenCV V4L2
            ret, frame = self._cap.read()
            if not ret:
                print("Error: Could not read frame from camera device=" + str(self._device_id))
                return
        self._current_frame = frame

    def close(self):
        # stop GST
        if self._backend == "gst_gi" and self._gst is not None:
            self._gst.stop()
            self._gst = None
        # Release OpenCV cap object
        if self._cap is not None:
            self._cap.release()
            self._cap = None
   
    @staticmethod
    def fourcc_int_to_str(fourcc):
        return "".join([chr((int(fourcc) >> (8 * i)) & 0xFF) for i in range(4)])

    def get_meta_info(self):
        """
        Return a JSON-serializable dict describing this camera instance.
        """
        info = {
            "type": "Camera",
            "backend": "gstreamer" if self._use_gstreamer else "v4l2",
            "device_id": self._device_id,
            "device_node": f"/dev/video{self._device_id}" if isinstance(self._device_id, int) else str(self._device_id),
            "exists": os.path.exists(f"/dev/video{self._device_id}") if isinstance(self._device_id, int) else None,
            "video_format": self._video_format if not self._use_gstreamer else "from_pipeline",
            "is_opened": bool(self.is_opened()),
        }

        if self._use_gstreamer:
            info["gstreamer"] = {
                "pipeline": self._gst_pipeline
            }
        else:
            fourcc_int = int(self._cap.get(cv2.CAP_PROP_FOURCC))
            info["properties"] = {
                "width": int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(self._cap.get(cv2.CAP_PROP_FPS)),
                "fourcc": {
                    "int": fourcc_int,
                    "str": Camera.fourcc_int_to_str(fourcc_int)
                },
            }
        return info

    @staticmethod
    def gst_pipeline(device, width, height, fps):
        return (
            f"v4l2src device=/dev/video{device} ! "
            f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
            f"jpegdec ! videoconvert ! video/x-raw,format=BGR ! "
            f"appsink drop=true max-buffers=1 sync=false"
        )

class IRCamera(Camera):
    
    COLORMAPS_LIST = [cv2.COLORMAP_JET, cv2.COLORMAP_HOT, cv2.COLORMAP_MAGMA, cv2.COLORMAP_INFERNO, cv2.COLORMAP_PLASMA, cv2.COLORMAP_BONE, cv2.COLORMAP_SPRING, cv2.COLORMAP_AUTUMN, cv2.COLORMAP_VIRIDIS, cv2.COLORMAP_PARULA, cv2.COLORMAP_RAINBOW]
   
    #256x192 General settings
    width = 256 #Sensor width
    height = 192 #sensor height
    scale = 2.5 #scale multiplier
    newWidth = int(width*scale)
    newHeight = int(height*scale)
    alpha = 1.0 # Contrast control (1.0-3.0)
    font=cv2.FONT_HERSHEY_SIMPLEX
    dispFullscreen = False
    rad = 0 #blur radius
    threshold = 2
    hud = True
    recording = False
    elapsed = "00:00:00"
    snaptime = "None"


    # Enums
    class ColorMap(Enum):
        JET = 0
        HOT = 1
        MAGMA = 2
        INFERNO = 3
        PLASMA = 4
        BONE = 5
        SPRING = 6
        AUTUMN = 7
        VIRIDIS = 8
        PARULA = 9
        RAINBOW = 10
    class IRRenderMode(str, Enum):
        IMDATA_ONLY = "imdata_only"      # qualitative, no thermal normalization
        THERMAL_ONLY = "thermal_only"    # pure thermal colormap
        BLEND = "blend"                  # thermal colormap blended with imdata detail
    class IRNormMode(str, Enum):
        MINMAX = "minmax"                # per-frame min/max
        FIXED = "fixed"                  # fixed temp window


    def __init__(self, device_id, colormap: "IRCamera.ColorMap", use_gstreamer=False, gst_tee=False, gst_pipeline=None, gst_record_path=None, video_format="YUY2", norm_settings=("minmax", 80.0, 10.0)):
        if use_gstreamer and gst_pipeline is None:
            print("Using Default-Custom-Defined IR GStreamer Pipeline...")
            gst_pipeline = self.gst_pipeline(device_id, 256, 384, 25) #256x192 with 2x height due to two frames
        super().__init__(device_id, use_gstreamer=use_gstreamer, gst_tee=gst_tee, gst_pipeline=gst_pipeline, gst_record_path=gst_record_path, width=256, height=384, fps=25, video_format=video_format)
        self._colormap = IRCamera.COLORMAPS_LIST[colormap.value]
        self.colormap_name = colormap.name
        if self._backend == "opencv_v4l2":
            self._cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        norm_mode, norm_max, norm_min = norm_settings
        if norm_mode.lower() == "minmax":
            norm_mode = IRCamera.IRNormMode.MINMAX
        else:
            norm_mode = IRCamera.IRNormMode.FIXED

        # rendering and norm modes
        self.render_mode = IRCamera.IRRenderMode.THERMAL_ONLY
        #self.norm_mode = IRCamera.IRNormMode.FIXED # MINMAX or FIXED
        self.norm_mode = norm_mode

        # only used if norm_mode = FIXED
        self.fixed_tmin_c = norm_min
        self.fixed_tmax_c = norm_max
        self.sat_above = 0.0
        self.sat_below = 0.0
        #only ussed if render_mode = BLEND
        self.blend_alpha = 0.75

        # EMA Diff Map
        self._ema_thermal_bgr = None
        self._ema_thermal_float = None

        # Signed-change display parameters
        self._change_alpha = 0.08         # EMA update speed 0.08
        self._change_deadband_c = 0.15    # ignore tiny changes around 0 C 0.15
        self._change_display_max_c = 2.0  # +/- this many C maps to full intensity 2.0
        self._change_blur_kernel = 0      # 0 or 1 disables blur 5
        self._deadband_raw = self._change_deadband_c * 64.0
        self._display_max_raw = self._change_display_max_c * 64.0
        
        self._calculate_ema_diff_map = False

    def _build_gst_backend(self, *, device_id, gst_tee, gst_record_path, gst_bitrate, width, height, fps):
        # Ignore RGB-specific parameters; IR capture is fixed-format for your device.
        dev = f"/dev/video{device_id}" if isinstance(device_id, int) else str(device_id)
        return GstIrCaptureRawYuy2(
            device=dev,
            w=256,
            h=384,
            fps=25,
            drop=True
        )

    def _thermal_colormap_bgr(self) -> "np.ndarray":
        raw = self._raw_thermal_frame  # (192,256) uint16

        if self.norm_mode == IRCamera.IRNormMode.MINMAX:
            raw_lo = int(raw.min())
            raw_hi = int(raw.max())
        else:
            raw_lo = int((self.fixed_tmin_c + 273.15) * 64)
            raw_hi = int((self.fixed_tmax_c + 273.15) * 64)
            self.sat_above = float(np.mean(raw > raw_hi)) # calculate how much saturation there is above
            self.sat_below = float(np.mean(raw < raw_lo)) # and below

        den = max(raw_hi - raw_lo, 1)
        norm8 = ((raw.astype(np.float32) - raw_lo) * 255.0 / den).clip(0,255).astype(np.uint8)

        norm8_up = cv2.resize(norm8, (IRCamera.newWidth, IRCamera.newHeight), interpolation=cv2.INTER_CUBIC)
        return cv2.applyColorMap(norm8_up, self._colormap)


    def _thermal_signed_change_bgr(self):
        curr = self._raw_thermal_frame.astype(np.float32)

        # Optional smoothing to suppress shimmer/noise
        if self._change_blur_kernel and self._change_blur_kernel > 1:
            k = self._change_blur_kernel
            curr = cv2.GaussianBlur(curr, (k, k), 0)

        # First frame: initialize EMA and show blank image
        if self._ema_thermal_float is None:
            self._ema_thermal_float = curr.copy()
            h, w = curr.shape
            return np.zeros((h, w, 3), dtype=np.uint8)

        # Signed difference against EMA BEFORE updating EMA
        signed = curr - self._ema_thermal_float
        
        # Update EMA in current frame coordinates
        a = float(self._change_alpha)
        self._ema_thermal_float = a * curr + (1.0 - a) * self._ema_thermal_float

        # Split into positive (heating) and negative (cooling)
        pos = np.maximum(signed - self._deadband_raw, 0.0)
        neg = np.maximum((-1 * signed) - self._deadband_raw, 0.0)
        
        # Debug pos max neg max location
        #pos_idx = np.unravel_index(np.argmax(pos), pos.shape)
        #neg_idx = np.unravel_index(np.argmax(neg), neg.shape)
        #print("pos max:", float(pos[pos_idx]), "at", pos_idx)
        #print("neg max:", float(neg[neg_idx]), "at", neg_idx)

        # Suppress motion-like mixed positive/negative response
        overlap = np.minimum(pos, neg)
        pos = np.maximum(pos - overlap, 0.0)
        neg = np.maximum(neg - overlap, 0.0)
        
        # Scale to 8-bit
        pos_8 = np.clip(pos * (255.0 / self._display_max_raw), 0, 255).astype(np.uint8)
        neg_8 = np.clip(neg * (255.0 / self._display_max_raw), 0, 255).astype(np.uint8)

        # BGR output: blue for cooling, red for heating
        out = np.zeros((curr.shape[0], curr.shape[1], 3), dtype=np.uint8)
        out[..., 0] = neg_8   # Blue
        out[..., 2] = pos_8   # Red

        return out


    def update_frames(self):
        if self._backend == "gst_gi":
            frame, pts_ns = self._gst.get_latest()
            if frame is None:
                #print("Error: ir gst_gi frame is None")
                return
        else:
            ret, frame = self._cap.read()
            if not ret:
                print("Error: Could not read frame from IR camera device=" + str(self._device_id))
                return
        
        # Convert raw IR data to color-mapped image
        imdata,thdata = np.array_split(frame, 2)
        
        '''
        #grab data from the center pixel...
        lowbyte = int(thdata[96][128][0])
        highbyte = int(thdata[96][128][1])
        
        highbyte = highbyte << 8
        rawtemp = highbyte + lowbyte
        temp = (rawtemp/64)-273.15
        temp = round(temp,2)

        #find the max temperature in the frame
        lomax = int(thdata[...,1].max())
        posmax = int(thdata[...,1].argmax())
        #since argmax returns a linear index, convert back to row and col
        mcol,mrow = divmod(posmax,IRCamera.width)
        himax = int(thdata[mcol][mrow][0])
        lomax=lomax*256
        maxtemp = himax+lomax
        maxtemp = (maxtemp/64)-273.15
        maxtemp = round(maxtemp,2)


        #find the lowest temperature in the frame
        lomin = int(thdata[...,1].min())
        posmin = int(thdata[...,1].argmin())
        #since argmax returns a linear index, convert back to row and col
        lcol,lrow = divmod(posmin,IRCamera.width)
        himin = int(thdata[lcol][lrow][0])
        lomin=lomin*256
        mintemp = himin+lomin
        mintemp = (mintemp/64)-273.15
        mintemp = round(mintemp,2)

        #find the average temperature in the frame
        loavg = int(thdata[...,1].mean())
        hiavg = int(thdata[...,0].mean())
        loavg=loavg*256
        avgtemp = loavg+hiavg
        avgtemp = (avgtemp/64)-273.15
        avgtemp = round(avgtemp,2)
        '''
        raw_thermal_frame_fixed_point_kelvin = (thdata[...,1].astype(np.uint16) << 8) | thdata[...,0]
        self._raw_thermal_frame = (raw_thermal_frame_fixed_point_kelvin / 64.0) - 273.15

        raw_min = int(self._raw_thermal_frame.min())
        raw_max = int(self._raw_thermal_frame.max())
        raw_avg = float(self._raw_thermal_frame.mean())
        raw_center = int(self._raw_thermal_frame[96, 128])

        mintemp = raw_min
        maxtemp = raw_max
        avgtemp = raw_avg
        temp_center = raw_center

        self._min_temp = mintemp
        self._max_temp = maxtemp
        self._avg_temp = avgtemp
        self._center_temp = temp_center
        
        if self.render_mode in [IRCamera.IRRenderMode.IMDATA_ONLY, IRCamera.IRRenderMode.BLEND]:
            # Need imdata image
            # Convert the real image to BGR
            bgr_detail = cv2.cvtColor(imdata,  cv2.COLOR_YUV2BGR_YUYV)
            #Contrast
            bgr_detail = cv2.convertScaleAbs(bgr_detail, alpha=IRCamera.alpha)#Contrast
            #bicubic interpolate, upscale and blur
            bgr_detail = cv2.resize(bgr_detail,(IRCamera.newWidth,IRCamera.newHeight),interpolation=cv2.INTER_CUBIC)#Scale up!
            if IRCamera.rad>0:
                bgr_detail = cv2.blur(bgr_detail,(IRCamera.rad,IRCamera.rad))
        if self.render_mode in [IRCamera.IRRenderMode.THERMAL_ONLY, IRCamera.IRRenderMode.BLEND]:
            # Need thdata thermal data
            bgr_thermal = self._thermal_colormap_bgr() # <-- Make sure to call this after self._raw_thermal_frame is calculated as it uses that variable
            if self._calculate_ema_diff_map:
                self._ema_thermal_bgr = self._thermal_signed_change_bgr()

        if self.render_mode == IRCamera.IRRenderMode.IMDATA_ONLY:
            self._current_frame = cv2.applyColorMap(bgr_detail, self._colormap)
        elif self.render_mode == IRCamera.IRRenderMode.THERMAL_ONLY:
            self._current_frame = bgr_thermal
        else: 
            # blend thermal with grayscale detail for readability
            gray = cv2.cvtColor(bgr_detail, cv2.COLOR_BGR2GRAY)
            detail = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            a = float(self.blend_alpha)
            self._current_frame = cv2.addWeighted(bgr_thermal, a, detail, 1.0 - a, 0.0)

        # self._current_frame = cv2.applyColorMap(bgr, self._colormap)

    def get_raw_thermal_frame(self):
        return self._raw_thermal_frame

    def get_ema_thermal_temps(self):
        return self._ema_thermal_float

    def get_ema_thermal_bgr(self):
        return self._ema_thermal_bgr

    def get_temp_stats(self):
        return (getattr(self, "_min_temp", None),
                getattr(self, "_max_temp", None),
                getattr(self, "_avg_temp", None),
                getattr(self, "_center_temp", None))

    def get_fixed_norm_stats(self):
        return self.fixed_tmin_c, self.fixed_tmax_c, self.sat_below, self.sat_above

    def get_norm_mode(self):
        return self.norm_mode

    @staticmethod
    def gst_pipeline(device, width, height, fps):
        return (
            f"v4l2src device=/dev/video{device} ! "
            f"video/x-raw,format=YUY2,width={width},height={height},framerate={fps}/1 ! "
            f"videoconvert ! "
            f"appsink drop=1 max-buffers=1 sync=false"
        )

    def get_meta_info(self) -> dict:
        d = super().get_meta_info()
        d.update({
            "ir_raw_shape": [192, 256],
            "ir_raw_dtype": "uint16",
            "conversion": "temp_c = raw/64.0 - 273.15",
            "display_scale": float(IRCamera.scale),
            "display_size": [int(192 * IRCamera.scale), int(256 * IRCamera.scale)],  # be consistent (H,W) vs (W,H)
            "render_mode": self.render_mode.value,
            "norm_mode": self.norm_mode.value,
            "fixed_tmin_c": float(self.fixed_tmin_c),
            "fixed_tmax_c": float(self.fixed_tmax_c),
            "blend_alpha": float(self.blend_alpha),
            "colormap": self.colormap_name,
        })
        return d

