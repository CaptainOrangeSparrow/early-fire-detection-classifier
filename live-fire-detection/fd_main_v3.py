# Fire Distinguisher Main Program
# 3/9/26

# Written Michael Chung

import os
import time
import builtins
import inspect
import pathlib
import threading
import argparse

# Override prints for cleaner logging across our modules
orig_print = builtins.print
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
def tagged_print(*args, **kwargs):
    frame = inspect.currentframe().f_back
    try:
        file = frame.f_globals.get("__file__")

        if file:
            path = pathlib.Path(file).resolve()

            if PROJECT_ROOT in path.parents or path == PROJECT_ROOT:
                tag = path.stem
                thread = threading.current_thread().name
                orig_print(f"[{tag}:{thread}]", *args, **kwargs)
                return
    finally:
        del frame
    orig_print(*args, **kwargs)
builtins.print = tagged_print

# Do the rest of custom imports here
import constants
import datarecorder
from peripherals.cameras import IRCamera
from peripherals.sensor_suite import SensorSuite
from utilities.fps_tracker import FPSTracker
from utilities.key_handler import TerminalKeyWatcher, poll_quit_key
from utilities.single_instance import SingleInstance
from utilities.web_preview import generate_colorbar_png
from telemetry.telemetry_wrapper import TelemetryWrapper
from servo.fire_tracker import FireTracker, TrackerState
from servo.pan_tilt_tracking import (          # constants only — no factory fns
    PAN_PIN,  TILT_PIN,
    PAN_LIMITS, TILT_LIMITS,
    FRAME_W,  FRAME_H,
    HFOV_DEG, VFOV_DEG,
    PAN_KP,   PAN_KI,   PAN_KD,
    TILT_KP,  TILT_KI,  TILT_KD,
    PAN_ERROR_SIGN, TILT_ERROR_SIGN,
)
import real_time_ml_v3 as ml
from audio.soundthread_v2 import ThreadedSoundPlayer

class FireDistinguisher:

    def __init__(self, args):
        self.args = args
        
        # Init
        self.run_dir = "/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/" + constants.RECORDINGS_PARENT_DIR
        self.cmap = IRCamera.ColorMap[constants.IR_COLORMAP]
        generate_colorbar_png(os.path.join("utilities/static", "colorbar.png"), IRCamera.COLORMAPS_LIST[self.cmap.value], num_ticks=3)
        self.ir_norm_settings = ("FIXED", 150, 20) # ("MINMAX", 80, 10) (mode, max, min)

        # Sensor Hardware
        sensor_config = {
                "reg_id": constants.REG_CAMERA_DEVICE_ID,
                "ir_id": constants.IR_CAMERA_DEVICE_ID,
                "ir_colormap": self.cmap,
                "ir_norm_settings": self.ir_norm_settings,
                "use_gstreamer": False,
                "gst_tee": False,
                "run_dir": self.run_dir,
                "fps": constants.FPS,
                }
        self.sensorsuite = SensorSuite(sensor_config)

        # Data Recorder / Main GUI Init
        self.dr = datarecorder.DataRecorder(
            run_dir=self.run_dir,
            reg_id = constants.REG_CAMERA_DEVICE_ID,
            ir_id = constants.IR_CAMERA_DEVICE_ID,
            fps = constants.FPS,
            ir_colormap = self.cmap,
            ir_norm_settings = self.ir_norm_settings,
            sensorsuite = self.sensorsuite,
            console_status=False,
            terminal_quit = True,
            view_only = True,
            use_gstreamer = False,
            verbose = False
        )
        self.web = self.dr.get_web_app()

        # Telemetry System
        self.tw = TelemetryWrapper(sensors=self.sensorsuite.get_sensor_objects(), auto_switch=5, debug=True)
        self.tw.start()

        # Machine Learning
        self.vis_path = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/visible_yolov11n/best_rgb.engine'
        self.ir_path = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/infrared_yolov11n/best_ir.engine'
        self.meta_path = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/meta-learner/fire_meta_learner_v2.pkl'
        self.models = ml.initialize_fire_models(vis_path=self.vis_path, ir_path=self.ir_path, meta_path=self.meta_path)

        # Audio
        self.player = ThreadedSoundPlayer()
        ThreadedSoundPlayer.set_main_player(self.player)
        
        # Pan-Tilt Mount PID Controllers
        self.tracker = FireTracker(
            pan_pin=PAN_PIN,
            tilt_pin=TILT_PIN,
            pan_limits=PAN_LIMITS,
            tilt_limits=TILT_LIMITS,
            frame_w=FRAME_W,
            frame_h=FRAME_H,
            hfov_deg=HFOV_DEG,
            vfov_deg=VFOV_DEG,
            pan_kp=PAN_KP,   pan_ki=PAN_KI,   pan_kd=PAN_KD,
            tilt_kp=TILT_KP, tilt_ki=TILT_KI, tilt_kd=TILT_KD,
            scan_speed=1.5,
            track_speed=5.0,
            pan_sweep_time=4.0,
            track_loss_timeout=3.0,     # Time to wait after losing target before declaring "lost" and resuming scan
            scan_resume_delay=3.0,      # Time to wait after losing target before resuming scan   
            fire_coverage_min=0.0,
            fire_coverage_max=0.2,
            pan_error_sign=PAN_ERROR_SIGN,
            tilt_error_sign=TILT_ERROR_SIGN,
            on_fire_acquired=self._cb_fire_acquired,
            on_fire_lost=self._cb_fire_lost,
            debug=True,
        )

    def _cb_fire_acquired(self) -> None:
        # Runs in tracker callback asyncronously from main tick thread 
        print("Fire acquired - target detected. Stopping scan and tracking.")
        self.player.play(
            "/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/audio/library/discord_join_sfx.wav",
            volume=0.05,
        )
 
    def _cb_fire_lost(self) -> None:
        # Runs in tracker callback asyncronously from main tick thread
        print("Fire lost - target no longer detected. Resuming scan.")


    def _on_tick(self):
        # Perform the following on every 25Hz tick
        # Read Sensors
        snapshot = self.sensorsuite.get_snapshot()
        
        # Perform ML
        ml_results = ml.process_fused_detection(
            snapshot.reg.frame,
            snapshot.ir.frame,
            snapshot.ir.temp_frame, 
            self.models,
            returnAnnotatedImg=False
        )
        min_temp, max_temp, avg_temp, center_temp  = self.sensorsuite.get_sensor_objects().ir_camera.get_temp_stats()
        self.web.set_fire_subtext("Hello World!" + " Min temp =" + str(min_temp) + " Max temp = " + str(max_temp) + " Avg temp = " + str(avg_temp) + " Center temp = " + str(center_temp))
        
        # Pass ML results to Web Stream
        self.web.set_fire_detected(ml_results["meta_decision"]["fire_detection_boolean"])
        self.web.update_ml_results(ml_results)
        
        #print(ml_results["raw_detections"]["visible"])
        #print(ml_results["raw_detections"]["infrared"])      
        
        # Update GUI
        self.dr.on_tick(snapshot, ml_results)    
    
        # Pan-Tilt Tracking: pass ml results to tracker and update pan-tilt angles accordingly
        self.tracker.update(ml_results)
      

    def program_start(self):
        # Main clock
        period = 1.0 / constants.FPS
        next_time = time.perf_counter()

        self.running = True
        while self.running:
            now = time.perf_counter()
            
            # Regulate to 25 Hz - comment out to go as fast as possible
            #if now < next_time:
                #time.sleep(next_time - now)
                #continue

            # ----- detect latency lateness -----
            lateness = now - next_time

            if lateness > period:
                skipped = int(lateness // period)
                # print(
                #     f"WARNING: main loop late by {lateness*1000:.1f} ms "
                #     f"(skipped {skipped} tick{'s' if skipped > 1 else ''})"
                # )

                # reset schedule
                next_time = now

            self._check_terminal_key()
            if not self.running:
                break

            self._on_tick()
            next_time += period

    def _check_terminal_key(self):
        if poll_quit_key():
            print("\nQuitting...")
            #if not self.view_only: # if not self.view_only
            #    print("Saving Data and Recordings...\n")
            #else:
            #    print()

            print() # if the above is uncommented, this was the else condition print, so must be removed when uncommenting.
            self.stop_and_close()

    def stop_and_close(self):
        # Cleanup
        if not hasattr(self, "running"):
            print("Trying to stop, but self.running is None! Perhaps the program has not started yet?")
        if not self.running:
            return
        self.running = False

        # Other cleanup
        self.dr.stop_and_close()
        self.tw.stop()

        # cancels timers, callbacks, and halts mount
        self.tracker.shutdown(center=True)  
        
        self.player.close()

        time.sleep(1) # Wait for sensor consumers to stop

        self.sensorsuite.stop_and_close()
def main():

    # Arg parser
    p = argparse.ArgumentParser(description="Main GUI")

    # Only allow one instance of this to run
    lock = SingleInstance("/tmp/jetson_main-program.lock")
    try:
        lock.acquire()
    except RuntimeError as e:
        print()
        print(str(e))
        print("Another instance of this script is already running!\n")
        raise SystemExit(1)
    
    fd = FireDistinguisher(p.parse_args())

    with TerminalKeyWatcher():
        fd.program_start()

    print("Closing App.\n")

if __name__ == "__main__":
    main()

