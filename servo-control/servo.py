
import Jetson.GPIO as GPIO
import time
import threading
import math

class Servo:
    def __init__(
        self,
        pin,
        frequency=50,
        min_duty=2.5,
        max_duty=12.5,
        min_angle=0.0,
        max_angle=180.0,
        transition_type='instant',
        transition_speed=1.0
    ):
        self.pin = pin
        self.frequency = frequency
        self.min_duty = min_duty
        self.max_duty = max_duty
        self.min_angle = min_angle
        self.max_angle = max_angle

        # Movement State
        self.current_angle = min_angle
        self.target_angle = min_angle
        self.transition_type = transition_type
        self.transition_speed = transition_speed

        self._lock = threading.Lock()

        # Setup Hardware
        GPIO.setup(self.pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, self.frequency)
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

    def set_angle(self, angle, transition_type=None, speed=None):
        """
        Public API to set a new target angle.
        Non-blocking - returns immediately.
        """
        angle = max(self.min_angle, min(self.max_angle, angle))
        with self._lock:
            self.target_angle = angle
            if transition_type is not None:
                self.transition_type = transition_type
            if speed is not None:
                self.transition_speed = speed

    def _move_worker(self):
        """
        Background thread that handles the movement interpolation.
        """
        while self._running:
            # Read state with minimal lock time
            with self._lock:
                start_angle = self.current_angle
                end_angle = self.target_angle
                transition_type = self.transition_type
                speed = self.transition_speed
            
            

            # Check if we need to move
            if abs(start_angle - end_angle) < 0.1:
                #print(f"stop")
                time.sleep(0.02)
                continue

            # Calculate next angle (NO LOCK HELD)
            next_angle = self._calculate_next_angle(
                start_angle, end_angle, transition_type, speed
            )

            # Update current angle with minimal lock time
            with self._lock:
                self.current_angle = next_angle

            # Apply to hardware (NO LOCK HELD)
            self._apply_angle(next_angle)
            #print(f"moving")
            # Sleep (NO LOCK HELD)
            time.sleep(0.02)

    def _calculate_next_angle(self, start_angle, end_angle, transition_type, speed):
        """Calculate next angle position without holding any locks"""
        
        if transition_type == 'instant':
            return end_angle

        elif transition_type == 'linear':
            direction = 1 if end_angle > start_angle else -1
            step = speed * direction
            if abs(step) > abs(end_angle - start_angle):
                return end_angle
            else:
                return start_angle + step

        elif transition_type == 's-curve':
            direction = 1 if end_angle > start_angle else -1
            error = abs(end_angle - start_angle)

            # Improved s-curve: uses remaining distance
            # Map error to 0-1 range based on a reasonable total movement
            normalized_error = error / 90.0  # Normalize to 0-2 range
            
            # Sigmoid function for smooth acceleration/deceleration
            # Center it so we get the S-curve shape
            x = (normalized_error - 1.0) * 0.25  # Map to -0.5 to +0.5
            sigmoid = 1.0 / (1.0 + math.exp(-x))
            
            # Scale speed by sigmoid (0.5 to 1.0 range for smoother motion)
            effective_step = speed * (0.5 + sigmoid * 0.5)
            step = effective_step * direction

            if abs(step) > error:
                return end_angle
            else:
                return start_angle + step

        elif transition_type == 'ease-out-quad':
            direction = 1 if end_angle > start_angle else -1
            error = abs(end_angle - start_angle)

            # Quadratic ease-out: starts fast, ends slow
            # Normalize error to 0-1 range
            t = min(error / 90.0, 1.0)
            # Ease-out quad: 1 - (1-t)^2
            factor = 1.0 - (1.0 - t) ** 2
            
            # Ensure minimum speed to avoid stalling
            effective_step = speed * max(factor, 0.1)
            step = effective_step * direction

            if abs(step) > error:
                return end_angle
            else:
                return start_angle + step

        else:
            return end_angle

    def _apply_angle(self, angle):
        """Internal function to write to hardware"""
        duty = self.angle_to_duty(angle)
        self.pwm.ChangeDutyCycle(duty)

    def stop(self):
        self.pwm.ChangeDutyCycle(0.0)

    def cleanup(self):
        self._running = False
        self._worker_thread.join(timeout=1.0)
        self.stop()
        self.pwm.stop()
