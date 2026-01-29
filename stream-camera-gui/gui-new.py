"""
Author: Michael Chung
Date: November 23, 2025
ECE 364D
"""

import sys
from PySide6.QtCore import Qt, QTimer, QDateTime, QSize, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QSizePolicy,
    QToolButton,
)
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QImage, QPixmap

import cv2
import numpy as np

from peripherals.cameras import Camera, IRCamera
import constants

class CameraThread(QThread):
    new_frame = Signal(object)  # emits numpy array frame

    def __init__(self, camera_obj, parent=None):
        super().__init__(parent)
        self.camera = camera_obj
        self.running = True

    def run(self):
        while self.running:
            self.camera.update_frames()
            frame = self.camera.get_latest_frame()
            if frame is not None:
                self.new_frame.emit(frame)
            self.msleep(30)  # ~33 fps

    def stop(self):
        self.running = False
        self.wait()
        self.camera.close()


class FrameWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #000000;")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def update_frame(self, frame):
        if frame is None:
            return
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888)
        pix = QPixmap.fromImage(qimg)
        pix = pix.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pix)

    def resizeEvent(self, event):
        if self.pixmap():
            self.setPixmap(self.pixmap().scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        super().resizeEvent(event)

################################################################

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Fire Distinguisher v1.0")
        self.resize(960, 540)

        # top-level dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #000000;
            }
            QLabel {
                color: #FFFFFF;
            }
            QPushButton, QToolButton {
                color: #FFFFFF;
                background-color: #000000;
                border: 1px solid #FFFFFF;
                padding: 6px 10px;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: #222222;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # =============== TOP AREA ==================
        top_area = QWidget()
        top_layout = QHBoxLayout(top_area)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(20)

        # ----- Left: title + system text -----
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        title_label = QLabel(
            'Fire <span style="color:#FF3333;">Distinguisher</span> v1.0'
        )
        title_label.setTextFormat(Qt.RichText)
        title_label.setStyleSheet("font-size: 18px;")

        system_label_title = QLabel("System is:")
        system_label_title.setStyleSheet("font-size: 14px;")

        self.system_state_label = QLabel("Active")
        self.system_state_label.setStyleSheet(
            "font-size: 36px; font-weight: bold; color: #8FE3B0;"
        )

        # horizontal light line under left block
        hline = QFrame()
        hline.setFrameShape(QFrame.HLine)
        hline.setFrameShadow(QFrame.Plain)
        hline.setStyleSheet("color: #888888;")

        left_layout.addWidget(title_label)
        left_layout.addWidget(hline)
        left_layout.addWidget(system_label_title)
        left_layout.addWidget(self.system_state_label)

        # ----- Center-left: date / time -----
        dt_box = QWidget()
        dt_layout = QVBoxLayout(dt_box)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        dt_layout.setSpacing(2)
        dt_layout.addStretch()

        self.date_label = QLabel("11/23")
        self.time_label = QLabel("23:17:04")

        self.date_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.date_label.setStyleSheet("font-size: 14px;")
        self.time_label.setStyleSheet("font-size: 18px;")

        dt_layout.addWidget(self.date_label)
        dt_layout.addWidget(self.time_label)

        # ----- Center: big status box -----
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.Box)
        status_frame.setLineWidth(0.5)
        status_frame.setStyleSheet(
            "QFrame { border: 1px solid #FFFFFF; background-color: #000000; }"
        )

        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.fire_status_label = QLabel("No fire Detected")
        self.fire_status_label.setAlignment(Qt.AlignCenter)
        self.fire_status_label.setStyleSheet(
            "font-size: 18px; font-weight: bold;"
        )
        status_layout.addWidget(self.fire_status_label)

        # ----- Right: Disarm / Record buttons -----
        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addStretch()

        self.disarm_button = QPushButton("Disarm")
        self.record_button = QPushButton("Record")

        self.disarm_button.setFixedWidth(110)
        self.record_button.setFixedWidth(110)

        self.disarm_button.clicked.connect(self.toggle_arm)
        self.record_button.clicked.connect(self.toggle_record)

        right_layout.addWidget(self.disarm_button)
        right_layout.addWidget(self.record_button)
        right_layout.addStretch()

        # Assemble top area
        top_layout.addWidget(left_box, stretch=3)
        top_layout.addWidget(dt_box, stretch=1)
        top_layout.addWidget(status_frame, stretch=4)
        top_layout.addWidget(right_box, stretch=2)

        main_layout.addWidget(top_area)

        # ----- Global separator line -----
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setStyleSheet("color: #888888;")
        main_layout.addWidget(separator)

        # =============== BOTTOM AREA ==================
        bottom_area = QWidget()
        bottom_layout = QHBoxLayout(bottom_area)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        # ----- LEFT NAVBAR -----
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(16)

        # icon-like buttons (placeholders)
        btn_home = QToolButton()
        btn_home.setIcon(QIcon("gui-assets/images/Nav-Home.png"))
        btn_home.setIconSize(QSize(32,32))
        btn_home.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                margin: 8px;
            }
            QToolButton:hover {
                background-color: #222222;
            }
            """)

        btn_saves = QToolButton()
        btn_saves.setIcon(QIcon("gui-assets/images/Nav-Saves.png"))
        btn_saves.setIconSize(QSize(32,32))
        btn_saves.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                margin: 8px;
            }
            QToolButton:hover {
                background-color: #222222;
            }
            """)

        btn_settings = QToolButton()
        btn_settings.setIcon(QIcon("gui-assets/images/Nav-Settings.png"))
        btn_settings.setIconSize(QSize(32,32))
        btn_settings.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                margin: 8px;
            }
            QToolButton:hover {
                background-color: #222222;
            }
            """)

        btn_code = QToolButton()
        btn_code.setIcon(QIcon("gui-assets/images/Nav-Code.png"))
        btn_code.setIconSize(QSize(32,32))
        btn_code.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                margin: 8px;
            }
            QToolButton:hover {
                background-color: #222222;
            }
            """)


        for b in (btn_home, btn_saves, btn_settings, btn_code):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        nav_layout.addWidget(btn_home)
        nav_layout.addWidget(btn_saves)
        nav_layout.addWidget(btn_settings)
        nav_layout.addWidget(btn_code)
        nav_layout.addStretch()

        # vertical line beside nav
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Plain)
        vline.setStyleSheet("color: #888888;")

        bottom_layout.addWidget(nav_container, stretch=0)
        bottom_layout.addWidget(vline, stretch=0)

        # ----- MAIN CONTENT GRID -----
        content_container = QWidget()
        grid = QGridLayout(content_container)
        grid.setContentsMargins(8, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        # helper to create content tilesi
        def create_tile(title: str, content_widget: QWidget | None = None) -> QFrame:
            frame = QFrame()
            frame.setFrameShape(QFrame.Box)
            frame.setLineWidth(1)
            frame.setStyleSheet(
                "QFrame { border: 1px solid #ffffff; background-color: #000000; }"
            )
            v = QVBoxLayout(frame)
            v.setContentsMargins(4, 4, 4, 4)
            v.setSpacing(4)

            # main content area (camera, etc.)
            if content_widget is None:
                placeholder = QWidget()
                placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                v.addWidget(placeholder, stretch=1)
            else:
                content_widget.setSizePolicy(
                    QSizePolicy.Ignored, QSizePolicy.Ignored
                )
                content_widget.setStyleSheet(
                    "QFrame { border: none; background-color: #000000; }"
                )
                v.addWidget(content_widget, stretch=1)

            # label footer (unchanged)
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 12px; font-weight: bold; color: #FFFFFF;")
             
            label_bg = QFrame()
            label_bg.setStyleSheet("QFrame { border: non; background-color: #333333; }")
            lab_layout = QVBoxLayout(label_bg)
            lab_layout.setContentsMargins(0, 2, 0, 2)
            lab_layout.addWidget(label)

            v.addWidget(label_bg, stretch=0)
            return frame

        self.visual_view = FrameWidget()
        self.ir_view = FrameWidget()

        visual_tile = create_tile("Visual Camera Feed", self.visual_view)
        ir_tile = create_tile("Infrared Camera Feed", self.ir_view)
        gas_tile = create_tile("Gas Composition Chart")
        ml_tile = create_tile("Machine Learning Text Stuff I guess Here")
        
        # Set sizes
        visual_tile.setMinimumSize(300, 250)
        ir_tile.setMinimumSize(300, 250)

        # place tiles in grid matching your mockup:
        # [ visual ][ infrared ][ gas (tall) ]
        # [   ml (spans two columns) ][ gas (continues) ]
        grid.addWidget(visual_tile, 0, 0, 1, 1)
        grid.addWidget(ir_tile, 0, 1, 1, 1)
        grid.addWidget(gas_tile, 0, 2, 2, 1)
        grid.addWidget(ml_tile, 1, 0, 1, 2)

        bottom_layout.addWidget(content_container, stretch=1)
        main_layout.addWidget(bottom_area, stretch=1)

        # =============== TIMER FOR CLOCK ==================
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_datetime)
        self.timer.start(1000)
        self.update_datetime()

        # state flags
        self.armed = True
        self.recording = False
        self.update_arm_button()

        # Start Camera Stream Threads
        # ===== CAMERA INTEGRATION =====
        VISUAL_DEVICE_ID = constants.RGB_CAMERA_DEVICE_ID
        IR_DEVICE_ID = constants.IR_CAMERA_DEVICE_ID

        self.visual_cam = Camera(VISUAL_DEVICE_ID)
        self.ir_cam = IRCamera(IR_DEVICE_ID, IRCamera.ColorMap.JET)

        self.visual_thread = CameraThread(self.visual_cam, self)
        self.visual_thread.new_frame.connect(self.visual_view.update_frame)
        self.visual_thread.start()

        self.ir_thread = CameraThread(self.ir_cam, self)
        self.ir_thread.new_frame.connect(self.ir_view.update_frame)
        self.ir_thread.start()

    # ---------- time ----------
    def update_datetime(self):
        now = QDateTime.currentDateTime()
        self.date_label.setText(now.toString("MM/dd"))
        self.time_label.setText(now.toString("HH:mm:ss"))

    # ---------- public API for statuses ----------
    def set_system_state(self, text: str):
        self.system_state_label.setText(text)

    def set_fire_status(self, text: str):
        self.fire_status_label.setText(text)

    # ---------- button handlers ----------
    def toggle_arm(self):
        self.armed = not self.armed
        self.update_arm_button()

    def update_arm_button(self):
        if self.armed:
            self.disarm_button.setText("Disarm")
            self.set_system_state("Active")
        else:
            self.disarm_button.setText("Arm")
            self.set_system_state("Inactive")

    def toggle_record(self):
        self.recording = not self.recording
        if self.recording:
            self.record_button.setText("Stop")
        else:
            self.record_button.setText("Record")
    
    def closeEvent(self, event):
        # stop threads and release cameras cleanly
        if hasattr(self, "visual_thread"):
            self.visual_thread.stop()
        if hasattr(self, "ir_thread"):
            self.ir_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set font
    font_id = QFontDatabase.addApplicationFont("gui-assets/fonts/Science_Gothic/ScienceGothic-VariableFont_CTRS,slnt,wdth,wght.ttf")
    family = QFontDatabase.applicationFontFamilies(font_id)[0]
    app.setFont(QFont(family, 14))


    w = MainWindow()
    w.show()
    sys.exit(app.exec())

