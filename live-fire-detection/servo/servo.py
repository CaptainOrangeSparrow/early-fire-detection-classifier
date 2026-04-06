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
        self.current_duty = 0.0

        # Limits (Software restrictions)
        self.min_limit = min_limit if min_limit is not None else min_angle
        self.max_limit = max_limit if max_limit is not None else max_angle

        # Movement State
        self.current_angle = self.min_limit
        self.target_angle = self.min_limit
        self._move_start_angle = self.min_limit
        self.transition_type = transition_type
        self.transition_speed = transition_speed

        self._lock = threading.Lock()

        # PWM State Management
        self._pwm_is_active = False
        self._completion_time = 0.0

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
        self.current_duty = duty
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

    def set_transition(self, transition_type):
        self.check_transition(transition_type)
        with self._lock:
            self.transition_type = transition_type

    def check_transition(self, transition_type):
        valid_transitions = ['instant', 'linear', 's-curve', 'ease-out-quad', 'ease-in-out-quad', 'sine']
        if transition_type not in valid_transitions:
            raise ValueError(f"Invalid transition type. Valid options are: {valid_transitions}")

    def set_speed(self, speed: float | int):
        with self._lock:
            self.transition_speed = speed

    def set_angle(self, angle, transition_type=None, speed=None):
        """
        Public API to set a new target angle.
        Non-blocking - returns immediately.
        """
        angle = max(self.min_limit, min(self.max_limit, angle))

        with self._lock:
            self._move_start_angle = self.current_angle
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
            self.pwm.start(duty)
            self._pwm_is_active = True
        else:
            self.pwm.ChangeDutyCycle(duty)

    def _stop_pwm(self):
        """Stops the PWM signal to prevent jitter."""
        if self._pwm_is_active:
            self.pwm.ChangeDutyCycle(0.0)
            self._pwm_is_active = False

    def _move_worker(self):
        """
        Background thread that handles movement and PWM release.
        """
        while self._running:
            # 1. Read state atomically
            with self._lock:
                start_angle = self.current_angle
                end_angle = self.target_angle
                transition_type = self.transition_type
                speed = self.transition_speed
                move_start_angle = self._move_start_angle

            distance = abs(end_angle - start_angle)

            # 2. Check if we need to move
            if distance > 0.1:
                # Estimate how long this specific step or move will take.
                software_speed_deg_sec = speed * 50.0

                if transition_type == 'instant':
                    effective_speed = self.SG90_MAX_SPEED_DEG_PER_SEC
                else:
                    estimated_avg_speed = software_speed_deg_sec * 0.6
                    effective_speed = min(estimated_avg_speed, self.SG90_MAX_SPEED_DEG_PER_SEC)

                estimated_duration = (distance / effective_speed) + 0.05
                self._completion_time = time.time() + estimated_duration

                # Calculate next step
                next_angle = self._calculate_next_angle(
                    start_angle, end_angle, transition_type, speed, move_start_angle
                )

                # Update state
                with self._lock:
                    self.current_angle = next_angle

                # Apply PWM
                duty = self.angle_to_duty(next_angle)
                self._start_pwm(duty)

            else:
                # 3. At target - stop PWM to prevent jitter
                #self._stop_pwm()

                if time.time() > self._completion_time:
                    self._stop_pwm()

            # Loop frequency matched to servo PWM frequency
            time.sleep(1 / 500.0)

    def _calculate_next_angle(self, start_angle, end_angle, transition_type, speed, move_start_angle):
        direction = 1 if end_angle > start_angle else -1
        error = abs(end_angle - start_angle)
        reduction_factor = 2 #max(1.0, min(8.0, speed * 0.2)) 

        if transition_type == 'instant':
            return end_angle

        elif transition_type == 'linear':
            step = speed * direction
            step = step / reduction_factor
            step = math.copysign(max(abs(step), 0.5), direction)
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 's-curve':
            normalized_error = error / 90.0
            x = (normalized_error - 1.0) * 0.25
            sigmoid = 1.0 / (1.0 + math.exp(-x))
            effective_step = speed * (0.5 + sigmoid * 0.5)
            step = effective_step * direction
            step = step / reduction_factor
            step = math.copysign(max(abs(step), 0.5), direction)
            print(f"Effective Step: {effective_step}, Actual Step: {step}")
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'ease-out-quad':
            t = min(error / 90.0, 1.0)
            factor = 1.0 - (1.0 - t) ** 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            step = step / reduction_factor
            step = math.copysign(max(abs(step), 0.5), direction)
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'ease-in-out-quad':
            t = min(error / 90.0, 1.0)
            if t < 0.5:
                factor = 2 * t * t
            else:
                factor = 1 - (-2 * t + 2) ** 2 / 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            step = step / reduction_factor
            step = math.copysign(max(abs(step), 0.5), direction)
            return end_angle if abs(step) > error else start_angle + step

        elif transition_type == 'sine':
            t = min(error / 90.0, 1.0)
            factor = -(math.cos(math.pi * t) - 1) / 2
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction
            step = step / reduction_factor
            step = math.copysign(max(abs(step), 0.5), direction)
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
