import Jetson.GPIO as GPIO
import time
import threading
import math

class Servo:
    # SG90 Spec: 0.12s / 60 degrees -> ~500 degrees / second
    SG90_MAX_SPEED_DEG_PER_SEC = 500.0 

    def __init__(
        self,
        pin,
        frequency=50,
        min_duty=2.5,
        max_duty=12.5,
        min_angle=0.0,
        max_angle=180.0,
        transition_type='instant',
        transition_speed=1.0,
        min_limit=None,
        max_limit=None
    ):
        self.pin = pin
        self.frequency = frequency
        self.min_duty = min_duty
        self.max_duty = max_duty
        self.min_angle = min_angle
        self.max_angle = max_angle

        # Limits (Software restrictions)
        self.min_limit = min_limit if min_limit is not None else min_angle
        self.max_limit = max_limit if max_limit is not None else max_angle

        # Movement State
        self.current_angle = self.min_limit
        self.target_angle = self.min_limit
        self.transition_type = transition_type
        self.transition_speed = transition_speed

        self._lock = threading.Lock()
        
        # PWM State Management
        self._pwm_is_active = False
        self._completion_time = 0.0 # Timestamp when move should be finished

        # Setup Hardware
        GPIO.setup(self.pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, self.frequency)
        
        # Initialize with 0 duty cycle (OFF) to prevent jitter at startup
        self.pwm.start(0.0) 

        # Start Movement Thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._move_worker, daemon=True)
        self._worker_thread.start()

    def angle_to_duty(self, angle):
        angle = max(self.min_angle, min(self.max_angle, angle))
        span_angle = self.max_angle - self.min_angle
        span_duty = self.max_duty - self.min_duty
        duty = self.min_duty + (angle - self.min_angle) * span_duty / span_angle
        return duty

    def set_limits(self, min_limit, max_limit):
        if min_limit >= max_limit:
            raise ValueError("Min limit must be less than max limit")
        min_limit = max(self.min_angle, min_limit)
        max_limit = min(self.max_angle, max_limit)
        
        with self._lock:
            self.min_limit = min_limit
            self.max_limit = max_limit
            if self.target_angle < min_limit:
                self.target_angle = min_limit
            elif self.target_angle > max_limit:
                self.target_angle = max_limit

    def set_speed(self, speed: float | int):
        with self._lock: 
            self.transition_speed = speed


    def set_angle(self, angle, transition_type=None, speed=None):
        """
        Public API to set a new target angle.
        Non-blocking - returns immediately.
        """
        # Clamp to software limits
        angle = max(self.min_limit, min(self.max_limit, angle))
        
        with self._lock:
            # If we are updating a moving target, the worker loop will pick it up
            # and recalculate the completion time automatically.
            self.target_angle = angle
            if transition_type is not None:
                self.transition_type = transition_type
            if speed is not None:
                self.transition_speed = speed
                
    def get_angle(self):
        """
        Public API to get the current angle.
        This does not return the targeted angle,
        yet it returns the last set angle INTERNALLY.
        """
        with self._lock:
            angle = self.current_angle
        
        return angle
        

    def _start_pwm(self, duty):
        """Starts or updates the PWM signal."""
        if not self._pwm_is_active:
            # RPi.GPIO requires start() to initiate the pulse train
            self.pwm.start(duty)
            self._pwm_is_active = True
        else:
            self.pwm.ChangeDutyCycle(duty)

    def _stop_pwm(self):
        """Stops the PWM signal to prevent jitter."""
        if self._pwm_is_active:
            self.pwm.ChangeDutyCycle(0.0)
            # Optionally use pwm.stop() if ChangeDutyCycle(0) doesn't silence it enough
            # self.pwm.stop() 
            self._pwm_is_active = False

    def _move_worker(self):
        """
        Background thread that handles movement and PWM release.
        """
        while self._running:
            # 1. Read State
            with self._lock:
                start_angle = self.current_angle
                end_angle = self.target_angle
                transition_type = self.transition_type
                speed = self.transition_speed
            
            distance = abs(end_angle - start_angle)

            # 2. Check if we need to move
            if distance > 0.1:
                # --- ESTIMATION LOGIC ---
                # Calculate how long this specific step or move will take.
                
                # Determine speed in degrees per second
                # Software speed = speed param (deg/step) * 50 (steps/sec)
                software_speed_deg_sec = speed * 50.0
                
                # Calculate effective speed
                effective_speed = 0.0
                
                if transition_type == 'instant':
                    # Instant is limited only by hardware
                    effective_speed = self.SG90_MAX_SPEED_DEG_PER_SEC
                else:
                    # For eased movements, the 'speed' parameter is the peak step size.
                    # Average speed for eased movements is roughly 60% of peak speed.
                    # We use this average to estimate total time.
                    # We also clamp it to the hardware max speed.
                    estimated_avg_speed = software_speed_deg_sec * 0.6
                    effective_speed = min(estimated_avg_speed, self.SG90_MAX_SPEED_DEG_PER_SEC)
                
                # Calculate duration: Time = Distance / Speed
                # Add a small settling margin (0.05s) to ensure it reaches the spot
                estimated_duration = (distance / effective_speed) + 0.05
                
                self._completion_time = time.time() + estimated_duration
                # --- END ESTIMATION ---

                # Calculate next step
                next_angle = self._calculate_next_angle(
                    start_angle, end_angle, transition_type, speed
                )

                # Update state
                with self._lock:
                    self.current_angle = next_angle

                # Apply PWM (Ensure it is running)
                duty = self.angle_to_duty(next_angle)
                self._start_pwm(duty)

            else:
                # 3. IDLE / STOPPING LOGIC
                # We are at the target (or code thinks we are).
                # Check if we have passed the completion time.
                if time.time() > self._completion_time:
                    # Time to release the signal
                    self._stop_pwm()
            
            # Loop frequency
            time.sleep(0.02)

    def _calculate_next_angle(self, start_angle, end_angle, transition_type, speed):
        direction = 1 if end_angle > start_angle else -1
        error = abs(end_angle - start_angle)

        if transition_type == 'instant':
            return end_angle

        elif transition_type == 'linear':
            step = speed * direction
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 's-curve':
            normalized_error = error / 90.0
            x = (normalized_error - 1.0) * 0.25
            sigmoid = 1.0 / (1.0 + math.exp(-x))
            effective_step = speed * (0.5 + sigmoid * 0.5)
            step = effective_step * direction
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'ease-out-quad':
            t = min(error / 90.0, 1.0)
            factor = 1.0 - (1.0 - t) ** 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'ease-in-out-quad':
            t = min(error / 90.0, 1.0)
            if t < 0.5:
                factor = 2 * t * t
            else:
                factor = 1 - (-2 * t + 2) ** 2 / 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'sine':
            t = min(error / 90.0, 1.0)
            factor = -(math.cos(math.pi * t) - 1) / 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            return end_angle if abs(step) > error else start_angle + step

        else:
            return end_angle

    def stop(self):
        self._stop_pwm()

    def cleanup(self):
        self._running = False
        self._worker_thread.join(timeout=1.0)
        self.stop()
        self.pwm.stop()
