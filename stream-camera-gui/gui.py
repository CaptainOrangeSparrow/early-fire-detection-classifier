'''
Author: Moby Chiu
Date: November 18, 2025
Course: ECE364D

Modified by Michael Chung
Date: November 20, 2025
'''

import sys
import os
import cv2
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QImage, QPixmap, QFont

from peripherals.cameras import IRCamera

# update these paths with the appropriate camera type paths footage !!!
VISIBLE_VIDEO_PATH = "saved_recordings/repo_test_1_MC.mp4"
INFRARED_VIDEO_PATH = "saved_recordings/repo_test_2_AJ.mp4"
# Frame update speed in milliseconds (eg 30 fps is about 33ms)
FRAME_DELAY_MS = 33

IR_CAMERA_DEVICE_ID = 6

class VideoPlayerApp(QMainWindow):
    """
    A PySide6 application for displaying video streams (recordings + live IR) using OpenCV.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECE364D Camera Stream GUI")
        self.setGeometry(100, 100, 1000, 600)

        # state variables
        self.cap = None          # cv2.VideoCapture object for recorded videos
        self.ir_camera = None    # IRCamera instance for live IR stream
        self.playing = False
        self.source_type = None  # "file" or "ir_live"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        # create window appearance
        self._setup_ui()
        self.display_placeholder("Select a camera feed to begin playback.")

    def _setup_ui(self):
        """Sets up the main layout and widgets."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # main Layout: Controls (Left) and Video Display (Right)
        main_layout = QHBoxLayout(central_widget)

        # control Panel (Left Column)
        self.control_panel = QWidget()
        self.control_panel.setStyleSheet("background-color: #2c3e50; border-radius: 8px;")
        control_layout = QVBoxLayout(self.control_panel)
        control_layout.setContentsMargins(20, 20, 20, 20)

        # title label
        title_label = QLabel("Select Recording")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: white; margin-bottom: 10px;")
        control_layout.addWidget(title_label)

        # Saved Recordings Buttons
        # visible button
        self.visible_btn = QPushButton("Visible Camera (MP4)")
        self.visible_btn.clicked.connect(lambda: self.start_video(VISIBLE_VIDEO_PATH))
        self.visible_btn.setFixedSize(200, 50)
        self.visible_btn.setStyleSheet(
            "background-color: #3498db; color: white; border-radius: 6px; padding: 10px;"
        )
        control_layout.addWidget(self.visible_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # infrared recording button
        self.infrared_btn = QPushButton("Infrared Camera (MP4)")
        self.infrared_btn.clicked.connect(lambda: self.start_video(INFRARED_VIDEO_PATH))
        self.infrared_btn.setFixedSize(200, 50)
        self.infrared_btn.setStyleSheet(
            "background-color: #e74c3c; color: white; border-radius: 6px; padding: 10px;"
        )
        control_layout.addWidget(self.infrared_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # NEW: Live IR camera button
        self.ir_live_btn = QPushButton("Live IR Camera")
        self.ir_live_btn.clicked.connect(self.start_ir_live)
        self.ir_live_btn.setFixedSize(200, 50)
        self.ir_live_btn.setStyleSheet(
            "background-color: #8e44ad; color: white; border-radius: 6px; padding: 10px;"
        )
        control_layout.addWidget(self.ir_live_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # "stop" Button
        self.stop_btn = QPushButton("STOP Playback")
        self.stop_btn.clicked.connect(self.stop_video)
        self.stop_btn.setFixedSize(200, 50)
        self.stop_btn.setStyleSheet(
            "background-color: #95a5a6; color: white; border-radius: 6px; padding: 10px;"
        )
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # adding a stretch to push controls to the top
        control_layout.addStretch()

        # Adding control panel to the main layout
        main_layout.addWidget(self.control_panel)

        # Video Display Area (Right Column)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #34495e; border-radius: 8px;")

        # add video label to the main layout and make it stretch
        main_layout.addWidget(self.video_label)
        main_layout.setStretchFactor(self.video_label, 1)

    def display_placeholder(self, message):
        """Displays a message in the video area when no video is playing."""
        self.video_label.setText(
            f"<div style='color: white; font-size: 18px; padding: 50px;'>{message}</div>"
        )
        self.video_label.setPixmap(QPixmap())  # Clear any image

    @Slot()
    def stop_video(self):
        """Stops the current video playback (file or live IR)."""
        if self.timer.isActive():
            self.timer.stop()

        # Release file-based capture
        if self.cap is not None:
            if isinstance(self.cap, cv2.VideoCapture) and self.cap.isOpened():
                self.cap.release()
            self.cap = None

        # Release IR camera
        if self.ir_camera is not None:
            self.ir_camera.close()
            self.ir_camera = None

        self.playing = False
        self.source_type = None

        # Reset button states
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "background-color: #95a5a6; color: white; border-radius: 6px; padding: 10px;"
        )
        self.visible_btn.setEnabled(True)
        self.infrared_btn.setEnabled(True)
        self.ir_live_btn.setEnabled(True)

        self.display_placeholder("Playback stopped. Select another feed.")

    @Slot()
    def start_video(self, path):
        """Starts video playback from the given path (recorded file)."""
        # Stop any currently playing stream
        if self.playing:
            self.stop_video()

        # checking if the file exists
        if not os.path.exists(path):
            QMessageBox.critical(self, "File Error", f"Video file not found at: {path}")
            self.display_placeholder(f"ERROR: File not found at {os.path.basename(path)}")
            return

        # initializing video capture
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "Video Error", f"Could not open video file: {path}")
            self.display_placeholder(f"ERROR: Could not open {os.path.basename(path)}")
            self.cap = None
            return

        # start the playback
        self.playing = True
        self.source_type = "file"

        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet(
            "background-color: #c0392b; color: white; border-radius: 6px; padding: 10px;"
        )

        self.visible_btn.setEnabled(False)
        self.infrared_btn.setEnabled(False)
        self.ir_live_btn.setEnabled(False)

        # clear any placeholder text
        self.video_label.setText("")

        # start the frame update timer
        self.timer.start(FRAME_DELAY_MS)

    @Slot()
    def start_ir_live(self):
        """Starts real-time IR camera stream using IRCamera."""
        # Stop any currently playing stream
        if self.playing:
            self.stop_video()

        # Device index may need to be adjusted (0, 1, "/dev/video2", etc.)
        device_id = IR_CAMERA_DEVICE_ID
        try:
            self.ir_camera = IRCamera(device_id, IRCamera.ColorMap.JET)
        except Exception as e:
            QMessageBox.critical(self, "IR Camera Error", f"Failed to create IR camera: {e}")
            self.ir_camera = None
            self.display_placeholder("ERROR: Could not initialize IR camera.")
            return

        # Optionally check underlying capture if needed
        # (IRCamera already prints error if it fails to open)
        if self.ir_camera.get_latest_frame() is None:
            # It might not have grabbed a frame yet; try one read
            self.ir_camera.update_frames()

        # Start streaming if we can
        self.playing = True
        self.source_type = "ir_live"

        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet(
            "background-color: #c0392b; color: white; border-radius: 6px; padding: 10px;"
        )

        self.visible_btn.setEnabled(False)
        self.infrared_btn.setEnabled(False)
        self.ir_live_btn.setEnabled(False)

        # clear any placeholder text
        self.video_label.setText("")

        # start the frame update timer
        self.timer.start(FRAME_DELAY_MS)

    @Slot()
    def update_frame(self):
        """Reads a frame and updates the GUI, depending on the active source."""
        if not self.playing:
            return

        frame = None

        if self.source_type == "file":
            if self.cap is None or not self.cap.isOpened():
                self.stop_video()
                self.display_placeholder("ERROR: Video capture lost.")
                return

            ret, f = self.cap.read()
            if not ret:
                # Video finished
                self.stop_video()
                self.display_placeholder("Video playback finished.")
                return

            frame = f

        elif self.source_type == "ir_live":
            if self.ir_camera is None:
                self.stop_video()
                self.display_placeholder("ERROR: IR camera not available.")
                return

            self.ir_camera.update_frames()
            f = self.ir_camera.get_latest_frame()
            if f is None:
                # Could not read frame — keep trying for a bit or stop
                print("Warning: No frame from IR camera.")
                return
            frame = f

        else:
            # Unknown source type
            self.stop_video()
            self.display_placeholder("No active source.")
            return

        # At this point, `frame` should be a BGR image (both file and IR camera give BGR)
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape

        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        pixmap = QPixmap.fromImage(qt_image)

        scaled_pixmap = pixmap.scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.video_label.setPixmap(scaled_pixmap)


if __name__ == "__main__":
    # a simple check for files
    if not os.path.exists(VISIBLE_VIDEO_PATH) or not os.path.exists(INFRARED_VIDEO_PATH):
        print(
            "Note: One or both video paths are missing. "
            "Please replace 'repo_test_1_MC.mp4' and 'repo_test_2_AJ.mp4' with your actual video files."
        )

    app = QApplication(sys.argv)
    window = VideoPlayerApp()
    window.show()
    sys.exit(app.exec())

