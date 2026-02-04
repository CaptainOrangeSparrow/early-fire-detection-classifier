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
        transition_speed=1.0 # degrees per tick (approx)
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
        self.transition_speed = transition_speed # Acts as speed or intensity factor
        
        self._lock = threading.Lock() # Thread safety
        
        # Setup Hardware
        GPIO.setup(self.pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, self.frequency)
        self.pwm.start(0.0)
        
        # Start Movement Thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._move_worker, daemon=True)
        self._worker_thread.start()

    def angle_to_duty(self, angle):
        # Clamp angle for calculation
        angle = max(self.min_angle, min(self.max_angle, angle))
        span_angle = self.max_angle - self.min_angle
        span_duty = self.max_duty - self.min_duty
        duty = self.min_duty + (angle - self.min_angle) * span_duty / span_angle
        return duty

    def set_angle(self, angle, transition_type=None, speed=None):
        """
        Public API to set a new target angle.
        Overrides previous movements if still in progress.
        """
        # Clamp target to physical limits
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
            with self._lock:
                start_angle = self.current_angle
                end_angle = self.target_angle
                
                # Check if we need to move
                if abs(start_angle - end_angle) < 0.01:
                    self._apply_angle(start_angle) # Ensure we are exactly at target
                    # Sleep to prevent CPU spinning when idle
                    time.sleep(0.05) 
                    continue

                # Determine Movement Profile
                if self.transition_type == 'instant':
                    self.current_angle = self.target_angle
                    step_size = 0 # Not used for instant

                elif self.transition_type == 'linear':
                    # Move 'speed' degrees towards target
                    direction = 1 if end_angle > start_angle else -1
                    step = self.transition_speed * direction
                    if abs(step) > abs(end_angle - start_angle):
                        self.current_angle = end_angle
                    else:
                        self.current_angle = start_angle + step

                elif self.transition_type == 's-curve':
                    # Use a sigmoid easing function on the step size
                    # We map the error to a curve, then take a step
                    direction = 1 if end_angle > start_angle else -1
                    error = abs(end_angle - start_angle)
                    
                    # Sigmoid math: scale error (0 to 180ish) to (-6 to 6) range roughly
                    # This creates the slow-fast-slow effect
                    normalized_input = (error / 90.0) * 5.0 
                    sigmoid = 1 / (1 + math.exp(-normalized_input)) # 0.0 to 1.0
                    
                    # Base speed is modulated by the sigmoid curve
                    # We add a small floor (0.1) so it doesn't stop completely mid-move
                    effective_step = self.transition_speed * (sigmoid + 0.1)
                    
                    step = effective_step * direction
                    
                    if abs(step) > abs(end_angle - start_angle):
                        self.current_angle = end_angle
                    else:
                        self.current_angle = start_angle + step

                elif self.transition_type == 'ease-out-quad':
                    # Starts fast, slows down drastically at end
                    direction = 1 if end_angle > start_angle else -1
                    error = abs(end_angle - start_angle)
                    
                    # Quadratic easing: x^2 (slows down as x gets small)
                    # Normalize error roughly 0-1 based on speed
                    t = error / (self.transition_speed * 10.0)
                    t = min(max(t, 0), 1)
                    factor = t * t 
                    
                    effective_step = self.transition_speed * factor
                    step = effective_step * direction
                    
                    if abs(step) > abs(end_angle - start_angle):
                        self.current_angle = end_angle
                    else:
                        self.current_angle = start_angle + step

                else:
                    # Default to instant if unknown type
                    self.current_angle = self.target_angle

                # Apply physics
                self._apply_angle(self.current_angle)
            
            # Control the tick rate of the loop (Precision vs CPU usage)
            # 20Hz = 50ms tick
            time.sleep(0.05)

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
