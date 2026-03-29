import asyncio
import threading
import cv2
from PIL import Image
import st7735
import cameras as cm
from adc import ADC
import matplotlib.pyplot as plt
import time
import numpy as np


DISPLAY_W = 128
DISPLAY_H = 160


class FrameStore:
    def __init__(self):
        self.rgb = None
        self.ir = None
        self.graph = None
        self.adc = None
        self.lock = asyncio.Lock()


class MultiViewDisplay:

    def __init__(self, preview=False, debug=False):

        self.debug = debug
        self.preview = preview
        self.running = True

        self.view = "MultiView"

        self.store = FrameStore()

        self.rgb_cam = cm.Camera(0)
        self.ir_cam = cm.IRCamera(2, cm.IRCamera.ColorMap.INFERNO)
        
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self.start_time = None
        self.frame_number = 0
        

        self.adc = ADC()

        self.disp = st7735.ST7735(
            port=0,
            cs=0,
            dc=31,
            rst=29,
            width=DISPLAY_W,
            height=DISPLAY_H,
            backlight= None,
            rotation=0,
            offset_left=0,
            offset_top=0,
            bgr=False,
            invert=False,
            spi_speed_hz=32_000_000
        )

        self.fig, self.ax = plt.subplots(figsize=(1.6, 1.28), dpi=100)

        self.fig.patch.set_facecolor("black")
        self.ax.set_facecolor("black")
        
        self.fig.subplots_adjust(
            left=0.23,
            right=0.98,
            top=0.95,
            bottom=0.25
        )

        self.channel_labels = [
            "MQ-4",
            "MQ-7",
            "MQ-138",
            "KY-026",
            "MiCS-6814",
            "MiCS-6814",
            "MiCS-6814"
        ]

        self.channel_colors = [
            "#00FFFF", "#FF6B6B", "#98FB98", "#FFD700",
            "#FF69B4", "#FFA500", "#7B68EE"
        ]

        self.lines = []

        for color, label in zip(self.channel_colors, self.channel_labels):
            line, = self.ax.plot([], [], color=color, linewidth=0.8, label=label)
            self.lines.append(line)

        self.ax.tick_params(colors="white", labelsize=6)
        self.ax.grid(True, alpha=0.3, color="white")

        self.ax.set_xlabel("Time", color="white", fontsize=6)
        self.ax.set_ylabel("Gas PPM (k)", color="white", fontsize=6)

        self.ax.legend(
            loc="upper left",
            fontsize=4,
            framealpha=0.25,
            facecolor="black",
            edgecolor="white",
            labelcolor="white",
            ncol=2
        )
        
        self.graph_data = [[] for _ in range(8)]

        self.fig.canvas.draw()
        self._bg = self.fig.canvas.copy_from_bbox(self.ax.bbox)

        # Mark lines as animated
        for line in self.lines:
            line.set_animated(True)

        # Fix axis limits upfront — don't call set_xlim/set_ylim in the loop
        self.ax.set_xlim(0, 50)
        self.ax.set_ylim(0, 50)  # adjust to your expected PPM range
        
    def request_view(self, name):
        self.view = name
            
    async def ir_task(self):

        while self.running:

            try:
                # TODO: remove the update frames; allow main script to handle updates
                self.ir_cam.update_frames()

                frame = self.ir_cam.get_latest_frame()

                if frame is not None:

                    async with self.store.lock:
                        self.store.ir = frame

            except Exception as e:
                print(f"IR camera error: {e}")

            await asyncio.sleep(1/25)
            
    async def rgb_task(self):

        while self.running:
            
            # TODO: remove the update frames; allow main script to handle updates
            self.rgb_cam.update_frames()

            frame = self.rgb_cam.get_latest_frame()

            if frame is not None:

                async with self.store.lock:
                    self.store.rgb = frame

            await asyncio.sleep(1/25)
            
    async def adc_task(self):

        while self.running:

            v0 = self.adc.read4_once(0)
            v1 = self.adc.read4_once(1)

            # TODO: remove above 2 lines and uncomment line below once Michael has implemented get_all_latest 
            # values = self.adc.get_all_latest()

            # TODO: remove line once once Michael has implemented a way to return all 8 values in a list
            values = v0 + v1    

            async with self.store.lock:
                self.store.adc = values

            await asyncio.sleep(1/25)
                    
    async def graph_task(self):
        while self.running:
            async with self.store.lock:
                vals = self.store.adc

            if vals is not None:
                for i, v in enumerate(vals):
                    if i >= len(self.graph_data):
                        break
                    self.graph_data[i].append(v)
                    self.graph_data[i] = self.graph_data[i][-50:]

                all_values = []
                max_len = 0

                for i, series in enumerate(self.graph_data[:len(self.lines)]):
                    self.lines[i].set_data(range(len(series)), series)
                    if series:
                        all_values.extend(series)
                        max_len = max(max_len, len(series))

                if all_values:
                    data_min = min(all_values)
                    data_max = max(all_values)
                    padding = (data_max - data_min) * 0.1 or 1

                    # Update limits and redraw background before blitting
                    self.ax.set_xlim(0, max(max_len, 10))
                    self.ax.set_ylim(data_min - padding, data_max + padding)
                    self.fig.canvas.draw()  # full redraw to sync background with new limits
                    self._bg = self.fig.canvas.copy_from_bbox(self.ax.bbox)  # update bg

                    self.fig.canvas.restore_region(self._bg)
                    for line in self.lines:
                        self.ax.draw_artist(line)
                    self.fig.canvas.blit(self.ax.bbox)

                    w, h = self.fig.canvas.get_width_height()
                    buf = np.frombuffer(self.fig.canvas.buffer_rgba(), dtype=np.uint8)

                    if buf.size != w * h * 4:
                        await asyncio.sleep(1/8)
                        continue

                    img = buf.reshape(h, w, 4)
                    graph = Image.fromarray(img).convert("RGB")

                    async with self.store.lock:
                        self.store.graph = graph

            await asyncio.sleep(1/8)
                        
    async def render_task(self):
        if self.start_time is None and self.debug:
            self.start_time = time.perf_counter()

        while self.running:

            async with self.store.lock:
                rgb = self.store.rgb
                ir = self.store.ir
                graph = self.store.graph

            frame = self.build_frame(rgb, ir, graph)

            self.output_frame(frame)

            if self.debug:
                self.frame_number += 1
                if self.frame_number % 50 == 0:
                    print(f"Frame {self.frame_number}: {round(self.frame_number / (time.perf_counter() - self.start_time), 2)} FPS")

            await asyncio.sleep(1/25) # Attempt 25 FPS display
                
    def build_frame(self, rgb, ir, graph):

        rgb = np.rot90(rgb)
        ir = np.rot90(ir)

        if self.view == "RGB":
            return self.prepare(rgb)

        if self.view == "IR":
            return self.prepare(ir)

        if self.view == "Gas":
            graph = graph.rotate(90, expand=True) # Rotate so that the graph is landscape
            return self.prepare(graph)

        return self.multiview(rgb, ir, graph)
        
    def multiview(self, rgb, ir, graph):

        canvas = Image.new("RGB", (128,160))

        if rgb is not None:

            rgb = self.prepare(rgb, (64,80))
            canvas.paste(rgb,(0,0))

        if ir is not None:

            ir = self.prepare(ir,(64,80))
            canvas.paste(ir,(64,0))

        if graph is not None:
            graph = graph.resize((128,80))
            canvas.paste(graph,(0,80))

        return canvas #.rotate(90,expand=True)
        
    def prepare(self, frame, size=(128,160)):

        if isinstance(frame, np.ndarray):
            # Conversion to RGB
            #frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = Image.fromarray(frame)

        return frame.resize(size, Image.BILINEAR)
            
    def output_frame(self, frame):

        self.disp.display(frame)

        # store latest frame for HTTP streaming
        with self._frame_lock:
            self._latest_frame = np.array(frame)

        if not self.preview:
            return

        img = np.array(frame)
        #img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        cv2.imshow("Telemetry", img)
        cv2.waitKey(1)
                
    async def run(self):

        tasks = [

            asyncio.create_task(self.rgb_task()),
            asyncio.create_task(self.ir_task()),
            asyncio.create_task(self.adc_task()),
            asyncio.create_task(self.graph_task()),
            asyncio.create_task(self.render_task())
        ]

        await asyncio.gather(*tasks)
                
    def get_latest_frame(self):

        with self._frame_lock:

            if self._latest_frame is None:
                return None

            return self._latest_frame.copy()
            
    def cleanup(self):

        self.running = False

        self.rgb_cam.close()
        self.ir_cam.close()

        plt.close("all")

        if self.preview:
            cv2.destroyAllWindows()