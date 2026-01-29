'''
Author: Michael Chung
Date: November 20, 2025
ECE 364D
'''

import cv2
import numpy as np
from enum import Enum

class Camera():

    def __init__(self, device_id):

        self._current_frame = None
        self._device_id = device_id
        self._cap = cv2.VideoCapture(device_id, cv2.CAP_V4L2)
        

        if not self._cap.isOpened():
            print("Error: Could not open camera device=" + str(self._device_id))

    def get_latest_frame(self):
        return self._current_frame

    def update_frames(self):
        ret, frame = self._cap.read()
        if not ret:
            print("Error: Could not read frame from camera device=" + str(self._device_id))
            return
        self._current_frame = frame

    def close(self):
        self._cap.release()


class IRCamera(Camera):
    
    COLORMAPS_LIST = [cv2.COLORMAP_JET, cv2.COLORMAP_HOT, cv2.COLORMAP_MAGMA, cv2.COLORMAP_INFERNO, cv2.COLORMAP_PLASMA, cv2.COLORMAP_BONE, cv2.COLORMAP_SPRING, cv2.COLORMAP_AUTUMN, cv2.COLORMAP_VIRIDIS, cv2.COLORMAP_PARULA, cv2.COLORMAP_RAINBOW]
   
    #256x192 General settings
    width = 256 #Sensor width
    height = 192 #sensor height
    scale = 3 #scale multiplier
    newWidth = width*scale
    newHeight = height*scale
    alpha = 1.0 # Contrast control (1.0-3.0)
    font=cv2.FONT_HERSHEY_SIMPLEX
    dispFullscreen = False
    rad = 0 #blur radius
    threshold = 2
    hud = True
    recording = False
    elapsed = "00:00:00"
    snaptime = "None"

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

    def __init__(self, device_id, colormap: "IRCamera.ColorMap"):
        super().__init__(device_id)
        self._colormap = IRCamera.COLORMAPS_LIST[colormap.value]
        self._cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

    def update_frames(self):
        ret, frame = self._cap.read()
        if not ret:
            print("Error: Could not read frame from IR camera device=" + str(self._device_id))
            return
        
        # Convert raw IR data to color-mapped image
        imdata,thdata = np.array_split(frame, 2)
        
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
        
        # Convert the real image to RGB
        bgr = cv2.cvtColor(imdata,  cv2.COLOR_YUV2BGR_YUYV)
        #Contrast
        bgr = cv2.convertScaleAbs(bgr, alpha=IRCamera.alpha)#Contrast
        #bicubic interpolate, upscale and blur
        bgr = cv2.resize(bgr,(IRCamera.newWidth,IRCamera.newHeight),interpolation=cv2.INTER_CUBIC)#Scale up!
        if IRCamera.rad>0:
            bgr = cv2.blur(bgr,(IRCamera.rad,IRCamera.rad))

        self._current_frame = cv2.applyColorMap(bgr, self._colormap)






