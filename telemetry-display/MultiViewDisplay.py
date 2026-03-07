import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import st7735
import time
from collections import deque
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import random
import cameras as cm
from adc import ADC
import threading

class LiveGraph:
    # Handles real-time graph generation
    CHANNEL_COLORS = [
        '#00FFFF', '#FF6B6B', '#98FB98', '#FFD700',
        '#FF69B4', '#FFA500', '#7B68EE'
    ]

    def __init__(self, max_points=50, frame_size=(128, 80)):
        self.frame_size = frame_size
        self.fig, self.ax = plt.subplots(figsize=tuple(ti/100 for ti in self.frame_size), dpi=100)
        self.fig.patch.set_facecolor('black')
        self.ax.set_facecolor('black')
        self.adc = ADC()
        
        adc0_names = ["MQ-4 (CH4)", "MQ-7 (CO)", "MQ-138 (VOCs)", "KY-026 Flame"]
        adc1_names = ["MiCS-6814 NO2", "MiCS-6814 NH3", "MiCS-6814 CO", None]
        self.adc.set_adc_channel_names(0, adc0_names)
        self.adc.set_adc_channel_names(1, adc1_names)

        self.channels = []
        for ch_idx, name in enumerate(adc0_names):
            if name is not None:
                self.channels.append((0, ch_idx, name))
        for ch_idx, name in enumerate(adc1_names):
            if name is not None:
                self.channels.append((1, ch_idx, name))

        self.data = {
            (adc_i, ch_i): deque(maxlen=max_points)
            for adc_i, ch_i, _ in self.channels
        }

        self.lines = {}
        for color, (adc_i, ch_i, label) in zip(self.CHANNEL_COLORS, self.channels):
            line, = self.ax.plot([], [], color=color, linewidth=0.8, label=label)
            self.lines[(adc_i, ch_i)] = line

        self.ax.tick_params(colors='white', labelsize=6)
        self.ax.grid(True, alpha=0.3, color='white')
        self.ax.set_xlabel('Time', color='white', fontsize=6)
        self.ax.set_ylabel('Gas PPM', color='white', fontsize=6)
        self.ax.legend(
            loc='upper left', fontsize=4, framealpha=0.3,
            facecolor='black', edgecolor='white', labelcolor='white', ncol=2
        )

        self._latest_frame = Image.new('RGB', self.frame_size, color=(0, 0, 0))
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()

        self._sensor_thread = threading.Thread(target=self._sensor_loop, daemon=True)
        self._sensor_thread.start()

        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()

    def _capture_loop(self):
        while not self._stop.is_set():
            try:
                self.video.update_frames()
                frame = self.video.get_latest_frame()
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb).resize(self.frame_size, Image.BILINEAR)
                with self._frame_lock:
                    self._latest_frame = img
            except Exception as e:
                print(f"Camera error: {e}")
            time.sleep(0.033)  # ~30hz cap

    def get_frame(self):
        with self._frame_lock:
            return self._latest_frame

    def release(self):
        self._stop.set()
        self.video.close()


    def _sensor_loop(self):
        """I2C reads are slow (~50ms), no need to spin"""
        while not self._stop.is_set():
            try:
                values = self.read_sensor()
                self.add_data(values)
            except Exception as e:
                print(f"Sensor read error: {e}")
            time.sleep(0.05)  # ~20hz, matches ADC speed

    def _render_loop(self):
        """Only re-render when new data actually arrived"""
        last_render = 0
        while not self._stop.is_set():
            now = time.perf_counter()
            if now - last_render >= (1/10):  # cap at 10fps render rate
                img = self._render_frame()
                with self._frame_lock:
                    self._latest_frame = img
                last_render = now
            else:
                time.sleep(0.005)  # yield GIL while waiting

    def _render_frame(self):
        has_data = any(len(d) > 0 for d in self.data.values())
        if has_data:
            all_values = []
            max_len = 0
            for (adc_i, ch_i), line in self.lines.items():
                series = list(self.data[(adc_i, ch_i)])
                line.set_data(range(len(series)), series)
                all_values.extend(series)
                max_len = max(max_len, len(series))

            data_min, data_max = min(all_values), max(all_values)
            padding = (data_max - data_min) * 0.1 or 1
            self.ax.set_xlim(0, max(max_len, 10))
            self.ax.set_ylim(data_min - padding, data_max + padding)

        self.fig.canvas.draw()
        buf = np.frombuffer(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
        buf = buf.reshape(self.fig.canvas.get_width_height()[::-1] + (4,))
        return Image.fromarray(buf, mode='RGBA').convert('RGB').resize(
            self.frame_size, Image.BILINEAR  # BILINEAR is faster than LANCZOS
        )

    def get_graph_image(self):
        """MultiViewDisplay calls this — just returns latest pre-rendered frame"""
        with self._frame_lock:
            return self._latest_frame

    def stop(self):
        self._stop.set()


    def read_sensor(self):
        adc0_values = self.adc.read4_once(0)
        adc1_values = self.adc.read4_once(1)
        return adc0_values + adc1_values

    def set_frame_size(self, size):
        if size is not None and isinstance(size, tuple) and len(size) == 2:
            self.frame_size = size
            self.fig.set_size_inches(tuple(ti/100 for ti in self.frame_size))

    def add_data(self, values):
        """
        values: flat list of 8 readings [adc0_ch0..3, adc1_ch0..3]
        Only appends to deques for non-None channels.
        """
        adc0_vals = values[:4]
        adc1_vals = values[4:]
        src = {0: adc0_vals, 1: adc1_vals}

        for adc_i, ch_i, _ in self.channels:
            self.data[(adc_i, ch_i)].append(src[adc_i][ch_i])
    
class VideoFeed:
    """Handles video frame extraction and resizing"""
    def __init__(self, video_type=None, target_size=(64, 80)):
        if video_type == "IR":
            self.video = cm.IRCamera(2, cm.IRCamera.ColorMap.INFERNO)
        elif video_type == "RGB":
            self.video = cm.Camera(0)
        else:
            raise ValueError(f"Current 'video_type': {video_type} - Specify either: IR, RGB")

        self.target_size = target_size
        
    def set_frame_size(self, size):
        if size is not None and isinstance(size, tuple) and len(size) == 2:
            self.frame_size = size
            self.fig.set_size_inches(tuple(ti/100 for ti in self.frame_size))
            # Force render thread to redraw at new size immediately
            with self._frame_lock:
                self._latest_frame = None
        
    def get_frame(self):
        """Get next frame as PIL Image"""
        self.video.update_frames()
        frame = self.video.get_latest_frame()
        
        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL and resize
        pil_image = Image.fromarray(frame_rgb)
        pil_image = pil_image.resize(self.target_size, Image.LANCZOS)
        
        return pil_image
    
    def release(self):
        # Release video capture
        self.video.close()

class MultiViewDisplay:
    # Main display controller
    def __init__(self):
        # Initialize display
        self.disp = st7735.ST7735(
            port=0,
            cs=0,
            dc=31,
            backlight=None,
            rst=29,
            width=128,
            height=160,
            rotation=0,
            invert=False,
            offset_left=0,
            offset_top=0,
            spi_speed_hz=16_000_000  # 32 MHz
        )
        self.current_view = "MultiView"
        self.view_names = ["MultiView", "RGB", "IR", "Gas"]
        
        # Initialize video feeds
        self.camera_feed = VideoFeed(video_type="RGB", target_size=(64, 80))
        self.ir_feed = VideoFeed(video_type="IR", target_size=(64, 80))
        
        # Initialize graph
        self.graph = LiveGraph(max_points=50, frame_size=(128, 80))
        
        # Performance tracking
        self.frame_count = 0
        self.start_time = time.time()
        
    def simulate_sensor_reading(self):
        # Generate fake gas sensor data
        # Simulate with some noise and drift
        base_value = 50 + 20 * np.sin(time.time() * 0.5)
        noise = random.uniform(-5, 5)
        return max(0, min(100, base_value + noise))
    
    def create_composite_frame(self):
        """Combine all views into single frame"""
        # Create base canvas
        canvas = Image.new('RGB', (128, 160), color=(0, 0, 0))
        
        # Get camera frame (top-left)
        camera_frame = self.camera_feed.get_frame()
        canvas.paste(camera_frame, (0, 0))
        
        # Get IR frame (top-right)
        ir_frame = self.ir_feed.get_frame()
        canvas.paste(ir_frame, (64, 0))
        
        # Add sensor data and get graph
        graph_img = self.graph.get_graph_image()
        canvas.paste(graph_img, (0, 80))
        
        return canvas
        
    def set_view(self, view_name):
        if view_name in self.view_names:
            self.current_view = view_name
            
            # Clear display to black to prevent ghosting from previous view
            blank = Image.new('RGB', (128, 160), color=(0, 0, 0))
            self.disp.display(blank)
            
            if self.current_view == "MultiView":
                self.camera_feed.set_frame_size((64, 80))
                self.ir_feed.set_frame_size((64, 80))
                self.graph.set_frame_size((128, 80))
            elif self.current_view == "RGB":
                self.camera_feed.set_frame_size((128, 160))
            elif self.current_view == "IR":
                self.ir_feed.set_frame_size((128, 160))
            elif self.current_view == "Gas":
                self.graph.set_frame_size((128, 160))
                        
    def get_current_view_frame(self):
        FULL = (128, 160)
        
        if self.current_view == "MultiView":
            return self.create_composite_frame()
        
        elif self.current_view == "RGB":
            frame = self.camera_feed.get_frame()
            return frame.resize(FULL, Image.BILINEAR) if frame.size != FULL else frame
        
        elif self.current_view == "IR":
            frame = self.ir_feed.get_frame()
            return frame.resize(FULL, Image.BILINEAR) if frame.size != FULL else frame
        
        elif self.current_view == "Gas":
            frame = self.graph.get_graph_image()
            if frame is None:
                return Image.new('RGB', FULL, color=(0, 0, 0))  # blank while loading
            return frame.resize(FULL, Image.BILINEAR) if frame.size != FULL else frame

    def run(self, target_fps=10, duration=60, live=True):
        # Main display loop
        frame_delay = 1.0 / target_fps
        end_time = time.time() + duration
        print(f"Starting multi-view display at {target_fps} FPS")
        if not live:
            print(f"Will run for {duration} seconds")
        else:
            print("Will run indefinitely")
        
        try:
            while (time.time() < end_time) or live:
                frame_start = time.time()
                
                # Create and display composite frame
                frame = self.get_current_view_frame()
                self.disp.display(frame)
                
                # Track performance
                self.frame_count += 1
                
                # Calculate FPS
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    actual_fps = self.frame_count / elapsed
                    if self.frame_count % 50 == 0:
                        print(f"Frame {self.frame_count}, FPS: {actual_fps:.2f}")
                
                # Maintain target frame rate
                frame_time = time.time() - frame_start
                if frame_time < frame_delay:
                    time.sleep(frame_delay - frame_time)
                    
        except KeyboardInterrupt:
            print("\nStopped by user")
        finally:
            self.cleanup()
    
    def cleanup(self):
        # Release resources
        print("Cleaning up...")
        self.camera_feed.release()
        self.ir_feed.release()
        plt.close('all')
        
        # Show final stats
        elapsed = time.time() - self.start_time
        avg_fps = self.frame_count / elapsed if elapsed > 0 else 0
        print(f"Total frames: {self.frame_count}")
        print(f"Average FPS: {avg_fps:.2f}")

# if __name__ == "__main__":
#     try:
#             display = MultiViewDisplay()
#             display.run(target_fps=10, live=True)
#     except Exception as e:
#         print(f"Error: {e}")
#         import traceback
#         traceback.print_exc()