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
from servo.pan_tilt_tracking import build_mount, build_pids, pixel_to_angle
from servo.pan_tilt_tracking import (
    FRAME_W, FRAME_H, HALF_HFOV_RAD, HALF_VFOV_RAD,
    PAN_ERROR_SIGN, TILT_ERROR_SIGN,
)
from servo.objcenter import ObjCenter 
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
        self.meta_path = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/meta-learner/fire_meta_learner.pkl'
        self.models = ml.initialize_fire_models(vis_path=self.vis_path, ir_path=self.ir_path, meta_path=self.meta_path)

        # Audio
        self.player = ThreadedSoundPlayer()
        ThreadedSoundPlayer.set_main_player(self.player)
        
        # Pan-Tilt Mount PID Controllers
        self.mount = build_mount()
        self.pid_pan, self.pid_tilt = build_pids()
        self.obj_finder = ObjCenter(frame_w=FRAME_W, frame_h=FRAME_H)
        self.track_end_time = None
        self.isTracking = False
        
        
        self.last_detection_time = None # Timestamp of the last valid detection, used for anti-blink persistence
        self.track_loss_timeout = 0.5 # seconds to wait after losing detection before resuming scan
        
        self.last_obj_x = None # Last known object x-coordinate, used for anti-blink persistence (hold position if briefly lost)
        self.last_obj_y = None # Last known object y-coordinate, used for anti-blink persistence (hold position if briefly lost)
        
        # Begin scanning immediately on startup assuming no fires
        self.mount.start_scan(pan_sweep_time=4, speed=1.5) 

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
        
        # Pan-Tilt Tracking
        (obj_x, obj_y), (cx, cy), fire_detected = self.obj_finder.update(ml_results, fire_coverage_threshold_min=0, fire_coverage_threshold_max=0.2) # aquire centroid and fire boolean from ML results

        now = time.perf_counter()

        # If fire detected, track it with PID; else handle potential loss and resume scan if lost for a while
        self.web.set_fire_detected(ml_results["meta_decision"]["fire_detection_boolean"])
        
        if fire_detected:

            print("FIRE True")
            self.player.play("/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/audio/library/discord_join_sfx.wav", volume=0.05)
            # Record last valid detection time for anti-blink persistence
            self.last_detection_time = now
            self.last_obj_x = obj_x
            self.last_obj_y = obj_y

            # If scan is active, stop it and enter tracking
            if self.mount.is_scanning():
                print("Fire detected - stopping scan, attempting to track.")
                print(
                    "\n****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n",
                    "****************************************************************************************\n"
                )

                self.mount.stop_scan()
                self.mount.set_speeds(speed=5)
                # Reinitialize PID state to prevent integral and derivative windup from scan
                self.pid_pan.initialize(difference_equation=True) 
                self.pid_tilt.initialize(difference_equation=True)
                self.track_end_time = None # Currently tracking so reset any previous track loss timer

            # If we were previously "not tracking" due to a brief dropout,
            # reacquire smoothly WITHOUT treating it as a full loss
            if not self.isTracking:
                print("Fire reacquired - continuing tracking.")
                self.isTracking = True
                self.track_end_time = None

            # Calculate pan/tilt errors in pixels
            dx_px = obj_x - cx
            dy_px = obj_y - cy

            # Convert pixel errors to angular errors in degrees
            error_pan = PAN_ERROR_SIGN * pixel_to_angle(dx_px, HALF_HFOV_RAD, FRAME_W)
            error_tilt = TILT_ERROR_SIGN * pixel_to_angle(dy_px, HALF_VFOV_RAD, FRAME_H)

            # Produce new pan/tilt angle updates (P-only for now)
            pan_update = self.pid_pan.update(error_pan, difference_equation=True)
            tilt_update = self.pid_tilt.update(error_tilt, difference_equation=True)

            # Calculate and set new pan/tilt positions
            new_pan = self.mount.get_pan() + pan_update
            new_tilt = self.mount.get_tilt() + tilt_update

            # Meta-logging for debugging and analysis
            print(f"Fire Located at (x={obj_x}, y={obj_y}) with confidence {ml_results['meta_decision']['confidence']:.2f}")
            print(f"Pixel error - dx: {dx_px} px, dy: {dy_px} px")
            print(f"Tracking fire - pan error: {error_pan:.2f} deg, tilt error: {error_tilt:.2f} deg")
            print(f"Updating mount position - new pan: {self.mount.get_pan():.2f} deg, new tilt: {self.mount.get_tilt():.2f} deg")
            print(f"PID outputs - pan update: {pan_update:.2f} deg, tilt update: {tilt_update:.2f} deg")
            print(f"FIRE True")

            # Update mount position
            self.mount.set_position(new_pan, new_tilt)

        else:
            # No detection THIS tick, but do not instantly declare target lost
            recently_seen = ( # Check if we have seen a valid detection within the timeout window
                self.last_detection_time is not None and
                (now - self.last_detection_time) <= self.track_loss_timeout
            )

            if self.isTracking and recently_seen:
                # Anti-detection blink hold: remain in tracking mode and hold current mount position
                # This prevents target blinking from toggling tracking state.
                time_since_seen = now - self.last_detection_time
                print(f"No fire detected this tick - holding track ({time_since_seen:.2f}s since last detection).")

            elif self.isTracking and not recently_seen:
                # True loss: only now declare the target lost
                self.isTracking = False
                self.track_end_time = now
                print(f"Lost fire - resuming scan after 3 seconds. "
                    f"(No detection for {now - self.last_detection_time:.2f}s)")

            # Resume scan only after prolonged true loss
            if (
                (not self.mount.is_scanning())         # We are currently tracking or just stopped tracking
                and (not self.isTracking)              # We are currently not tracking (already past anti-blink)
                and self.track_end_time is not None    # We have started the track loss timer
                and (now - self.track_end_time > 3.0) # Wait 3 seconds after loss before resuming scan, to prevent rapid toggling if target is near the edge of detection
            ):
                print(
                    "\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n",
                    "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
                )

                # Reset states for next tracking phase
                self.track_end_time = None
                self.last_detection_time = None
                self.last_obj_x = None
                self.last_obj_y = None

                print("No fire detected - starting scan.")
                self.mount.start_scan(pan_sweep_time=4, speed=1.5) # Starts scan returning to bottom corner
        

        # Pass ML results to Web Stream
        self.web.update_ml_results(ml_results)

        # Update GUI
        self.dr.on_tick(snapshot, ml_results)

        #print(ml_results["raw_detections"]["visible"])
        #print(ml_results["raw_detections"]["infrared"])            

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

        self.mount.stop_scan()
        self.mount.shutdown(center=True)
        
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

