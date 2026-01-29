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

class LiveGraph:
    # Handles real-time graph generation
    def __init__(self, max_points=50):
        self.data = deque(maxlen=max_points)
        self.fig, self.ax = plt.subplots(figsize=(1.28, 0.8), dpi=100)
        self.fig.patch.set_facecolor('black')
        self.ax.set_facecolor('black')
        
    def add_data(self, value):
        # Add new sensor reading
        self.data.append(value)
    
    def get_graph_image(self):
        # Generate graph as PIL Image
        self.ax.clear()
        
        if len(self.data) > 0:
            self.ax.plot(list(self.data), color='#00FF00', linewidth=2)
            self.ax.set_xlim(0, max(len(self.data), 10))
            self.ax.set_ylim(0, 100)
            self.ax.tick_params(colors='white', labelsize=6)
            self.ax.grid(True, alpha=0.3, color='white')
            self.ax.set_xlabel('Time', color='white', fontsize=6)
            self.ax.set_ylabel('Gas PPM', color='white', fontsize=6)
        
        # Save to buffer
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', 
                    facecolor='black', edgecolor='none', dpi=100)
        buf.seek(0)
        
        # Convert to PIL and resize
        img = Image.open(buf)
        img = img.resize((128, 80), Image.LANCZOS)
        buf.close()
        
        return img

class VideoFeed:
    """Handles video frame extraction and resizing"""
    def __init__(self, video_path, target_size=(64, 80)):
        self.video = cv2.VideoCapture(video_path)
        self.target_size = target_size
        
        if not self.video.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
    
    def get_frame(self):
        """Get next frame as PIL Image"""
        ret, frame = self.video.read()
        
        if not ret:
            # Loop video
            print("No Frame Found")
            self.video.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.video.read()
            
        if not ret:
            # Return blank frame if still failing
            return Image.new('RGB', self.target_size, color=(0, 0, 0))
        
        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL and resize
        pil_image = Image.fromarray(frame_rgb)
        pil_image = pil_image.resize(self.target_size, Image.LANCZOS)
        
        return pil_image
    
    def release(self):
        # Release video capture
        self.video.release()

class MultiViewDisplay:
    # Main display controller
    def __init__(self, camera_path, ir_path):
        # Initialize display
        self.disp = st7735.ST7735(
            port=0,
            cs=0,
            dc="PQ.06",
            backlight=None,
            rst="PQ.05",
            width=128,
            height=160,
            rotation=0,
            invert=False,
            offset_left=0,
            offset_top=0,
            spi_speed_hz=15000000  # 32 MHz
        )
        
        # Initialize video feeds
        self.camera_feed = VideoFeed(camera_path, target_size=(64, 80))
        self.ir_feed = VideoFeed(ir_path, target_size=(64, 80))
        
        # Initialize graph
        self.graph = LiveGraph(max_points=50)
        
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
        sensor_value = self.simulate_sensor_reading()
        self.graph.add_data(sensor_value)
        graph_img = self.graph.get_graph_image()
        canvas.paste(graph_img, (0, 80))
        
        # Optional: Add dividing lines
        draw = ImageDraw.Draw(canvas)
        draw.line([(64, 0), (64, 80)], fill=(255, 255, 255), width=1)  # Vertical
        draw.line([(0, 80), (128, 80)], fill=(255, 255, 255), width=1)  # Horizontal
        
        return canvas
    
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
                frame = self.create_composite_frame()
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

if __name__ == "__main__":
    # Replace with actual /dev video paths
    CAMERA_VIDEO = "camera_feed.mp4"
    IR_VIDEO = "ir_feed.mp4"
    
    try:
        display = MultiViewDisplay(CAMERA_VIDEO, IR_VIDEO)
        display.run(target_fps=10, live=True)  # Run for 60 seconds at 10 FPS
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
