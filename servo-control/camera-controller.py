#!/usr/bin/env python3
"""
Camera Mount Control Script
Interactive CLI for controlling 2-axis servo camera mount
"""

import sys
import tty
import termios
import time
from CameraMount2Axis import CameraMount2Axis

class CameraController:
    def __init__(self, pan_pin, tilt_pin):
        self.camera = CameraMount2Axis(
            pan_pin=pan_pin,
            tilt_pin=tilt_pin,
            transition_type='linear',
            transition_speed=2.0
        )
        
        # Control settings
        self.increment = 5.0  # Default step size for WASD
        self.transition_speed = 2.0
        self.transition_type = 'linear'
        
        # Available transition types
        self.transition_types = [
            'instant',
            'linear',
            's-curve',
            'ease-out-quad',
            'ease-in-out-quad',
            'sine'
        ]
        
        # Saved positions (can be customized)
        self.saved_positions = {
            '1': (90, 90),   # Center
            '2': (45, 90),   # Left
            '3': (135, 90),  # Right
            '4': (90, 45),   # Up
            '5': (90, 135),  # Down
        }
        
        self.running = True
        self.last_command = "Ready"
    
    def _clear_screen(self):
        """Clear terminal screen"""
        print('\033[2J\033[H', end='')
    
    def _refresh_display(self):
        """Refresh the display - called after each command"""
        self._clear_screen()
        self._print_status()
    
    def _print_status(self):
        """Print current status and controls"""
        print("=" * 70)
        print("  CAMERA MOUNT CONTROLLER")
        print("=" * 70)
        print()
        
        # Current position
        print(f"📍 Position:")
        print(f"   Pan:  {self.camera.pan.target_angle:6.1f}° (current: {self.camera.pan.current_angle:6.1f}°)")
        print(f"   Tilt: {self.camera.tilt.target_angle:6.1f}° (current: {self.camera.tilt.current_angle:6.1f}°)")
        print()
        
        # Settings
        print(f"⚙️  Settings:")
        print(f"   Transition: {self.transition_type}")
        print(f"   Speed:      {self.transition_speed:.1f}°/step")
        print(f"   Increment:  {self.increment:.1f}°")
        print()
        
        # Last command
        print(f"💬 Last: {self.last_command}")
        print()
        
        # Controls
        print("─" * 70)
        print("CONTROLS:")
        print("─" * 70)
        print("  WASD        → Move camera (W=up, S=down, A=left, D=right)")
        print("  Arrow Keys  → Same as WASD")
        print("  C           → Center position (90°, 90°)")
        print("  1-5         → Preset positions")
        print()
        print("  +/-         → Increase/decrease increment")
        print("  [/]         → Decrease/increase speed")
        print("  T           → Change transition type")
        print("  G           → Go to specific angles")
        print("  P           → Save current position to preset")
        print()
        print("  H           → Show help")
        print("  Q / ESC     → Quit")
        print("=" * 70)
    
    def _get_key(self):
        """Get single keypress without Enter"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            # Check for escape sequences (arrow keys)
            if ch == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    return f'\x1b[{ch3}'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    
    def _get_input(self, prompt):
        """Get user input with echo restored"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return input(prompt)
        except KeyboardInterrupt:
            return None
    
    def handle_wasd(self, key):
        """Handle WASD movement"""
        current_pan = self.camera.pan.target_angle
        current_tilt = self.camera.tilt.target_angle
        
        if key in ['a', 'A', '\x1b[D']:  # Left / Left Arrow
            new_pan = max(0, current_pan - self.increment)
            self.camera.set_pan(new_pan)
            self.last_command = f"Pan left to {new_pan:.1f}°"
        
        elif key in ['d', 'D', '\x1b[C']:  # Right / Right Arrow
            new_pan = min(180, current_pan + self.increment)
            self.camera.set_pan(new_pan)
            self.last_command = f"Pan right to {new_pan:.1f}°"
        
        elif key in ['w', 'W', '\x1b[A']:  # Up / Up Arrow
            new_tilt = max(0, current_tilt - self.increment)
            self.camera.set_tilt(new_tilt)
            self.last_command = f"Tilt up to {new_tilt:.1f}°"
        
        elif key in ['s', 'S', '\x1b[B']:  # Down / Down Arrow
            new_tilt = min(180, current_tilt + self.increment)
            self.camera.set_tilt(new_tilt)
            self.last_command = f"Tilt down to {new_tilt:.1f}°"
    
    def handle_increment(self, key):
        """Handle increment adjustment"""
        if key == '+' or key == '=':
            self.increment = min(45.0, self.increment + 1.0)
            self.last_command = f"Increment increased to {self.increment:.1f}°"
        elif key == '-' or key == '_':
            self.increment = max(1.0, self.increment - 1.0)
            self.last_command = f"Increment decreased to {self.increment:.1f}°"
    
    def handle_speed(self, key):
        """Handle speed adjustment"""
        if key == ']':
            self.transition_speed = min(10.0, self.transition_speed + 0.5)
            self.camera.pan.transition_speed = self.transition_speed
            self.camera.tilt.transition_speed = self.transition_speed
            self.last_command = f"Speed increased to {self.transition_speed:.1f}°/step"
        elif key == '[':
            self.transition_speed = max(0.5, self.transition_speed - 0.5)
            self.camera.pan.transition_speed = self.transition_speed
            self.camera.tilt.transition_speed = self.transition_speed
            self.last_command = f"Speed decreased to {self.transition_speed:.1f}°/step"
    
    def change_transition_type(self):
        """Interactive transition type selection"""
        self._clear_screen()
        print("=" * 70)
        print("  SELECT TRANSITION TYPE")
        print("=" * 70)
        print()
        for i, ttype in enumerate(self.transition_types, 1):
            marker = "→" if ttype == self.transition_type else " "
            print(f"  {marker} {i}. {ttype}")
        print()
        
        choice = self._get_input("Enter number (or press Enter to cancel): ")
        
        if choice and choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(self.transition_types):
                self.transition_type = self.transition_types[idx]
                self.camera.pan.transition_type = self.transition_type
                self.camera.tilt.transition_type = self.transition_type
                self.last_command = f"Transition changed to {self.transition_type}"
            else:
                self.last_command = "Invalid selection"
        else:
            self.last_command = "Transition change cancelled"
    
    def goto_position(self):
        """Go to specific angles"""
        self._clear_screen()
        print("=" * 70)
        print("  GO TO POSITION")
        print("=" * 70)
        print()
        
        pan_input = self._get_input("Enter Pan angle (0-180): ")
        if pan_input is None:
            self.last_command = "Go to cancelled"
            return
        
        tilt_input = self._get_input("Enter Tilt angle (0-180): ")
        if tilt_input is None:
            self.last_command = "Go to cancelled"
            return
        
        try:
            pan = float(pan_input)
            tilt = float(tilt_input)
            
            if 0 <= pan <= 180 and 0 <= tilt <= 180:
                self.camera.set_position(pan, tilt)
                self.last_command = f"Moving to Pan={pan:.1f}°, Tilt={tilt:.1f}°"
            else:
                self.last_command = "Angles must be between 0-180°"
        except ValueError:
            self.last_command = "Invalid input - must be numbers"
    
    def save_position(self):
        """Save current position to a preset slot"""
        self._clear_screen()
        print("=" * 70)
        print("  SAVE CURRENT POSITION")
        print("=" * 70)
        print()
        print(f"Current Position: Pan={self.camera.pan.target_angle:.1f}°, Tilt={self.camera.tilt.target_angle:.1f}°")
        print()
        print("Existing presets:")
        for key, (pan, tilt) in self.saved_positions.items():
            print(f"  {key}: Pan={pan:.1f}°, Tilt={tilt:.1f}°")
        print()
        
        slot = self._get_input("Save to slot (1-5): ")
        
        if slot in ['1', '2', '3', '4', '5']:
            self.saved_positions[slot] = (
                self.camera.pan.target_angle,
                self.camera.tilt.target_angle
            )
            self.last_command = f"Position saved to slot {slot}"
        else:
            self.last_command = "Save cancelled or invalid slot"
    
    def load_preset(self, key):
        """Load a preset position"""
        if key in self.saved_positions:
            pan, tilt = self.saved_positions[key]
            self.camera.set_position(pan, tilt)
            self.last_command = f"Loaded preset {key}: Pan={pan:.1f}°, Tilt={tilt:.1f}°"
        else:
            self.last_command = f"No preset saved in slot {key}"
    
    def show_help(self):
        """Show detailed help"""
        self._clear_screen()
        print("=" * 70)
        print("  HELP - CAMERA MOUNT CONTROLLER")
        print("=" * 70)
        print()
        print("MOVEMENT CONTROLS:")
        print("  W / ↑        - Tilt up")
        print("  S / ↓        - Tilt down")
        print("  A / ←        - Pan left")
        print("  D / →        - Pan right")
        print()
        print("QUICK POSITIONS:")
        print("  C            - Center (90°, 90°)")
        print("  1-5          - Load saved preset positions")
        print("  P            - Save current position to preset")
        print()
        print("SETTINGS:")
        print("  + / =        - Increase movement increment")
        print("  - / _        - Decrease movement increment")
        print("  ] / }        - Increase transition speed")
        print("  [ / {        - Decrease transition speed")
        print("  T            - Change transition type")
        print()
        print("OTHER:")
        print("  G            - Go to specific angles (manual input)")
        print("  H            - Show this help")
        print("  Q / ESC      - Quit program")
        print()
        print("TRANSITION TYPES:")
        print("  instant      - Jump immediately to target")
        print("  linear       - Constant speed movement")
        print("  s-curve      - Smooth acceleration/deceleration")
        print("  ease-out-quad    - Fast start, slow end")
        print("  ease-in-out-quad - Slow start, fast middle, slow end")
        print("  sine         - Very smooth motion")
        print()
        
        self._get_input("Press Enter to continue...")
        self.last_command = "Help displayed"
    
    def run(self):
        """Main control loop"""
        # Show initial display
        self._refresh_display()
        
        try:
            while self.running:
                key = self._get_key()
                
                # Movement keys
                if key in ['w', 'W', 'a', 'A', 's', 'S', 'd', 'D', 
                          '\x1b[A', '\x1b[B', '\x1b[C', '\x1b[D']:
                    self.handle_wasd(key)
                    self._refresh_display()
                
                # Center
                elif key in ['c', 'C']:
                    self.camera.center()
                    self.last_command = "Centered to 90°, 90°"
                    self._refresh_display()
                
                # Presets
                elif key in ['1', '2', '3', '4', '5']:
                    self.load_preset(key)
                    self._refresh_display()
                
                # Increment adjustment
                elif key in ['+', '=', '-', '_']:
                    self.handle_increment(key)
                    self._refresh_display()
                
                # Speed adjustment
                elif key in ['[', ']', '{', '}']:
                    self.handle_speed(key)
                    self._refresh_display()
                
                # Transition type
                elif key in ['t', 'T']:
                    self.change_transition_type()
                    self._refresh_display()
                
                # Go to position
                elif key in ['g', 'G']:
                    self.goto_position()
                    self._refresh_display()
                
                # Save position
                elif key in ['p', 'P']:
                    self.save_position()
                    self._refresh_display()
                
                # Help
                elif key in ['h', 'H']:
                    self.show_help()
                    self._refresh_display()
                
                # Quit
                elif key in ['q', 'Q', '\x1b']:
                    self.last_command = "Shutting down..."
                    self._refresh_display()
                    self.running = False
                    break
                
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            self.last_command = "Interrupted - shutting down..."
            self._refresh_display()
            self.running = False
        
        finally:
            self._cleanup()
    
    def _cleanup(self):
        """Clean shutdown"""
        print("\n\nShutting down camera controller...")
        time.sleep(0.5)
        self.camera.shutdown()
        print("Cleanup complete. Goodbye!")


def main():
    """Entry point"""
    print("=" * 70)
    print("  CAMERA MOUNT CONTROLLER")
    print("=" * 70)
    print()
    print("Initializing hardware...")
    print()
    
    # Default pins - modify as needed
    PAN_PIN = 33   # GPIO pin for pan servo
    TILT_PIN = 32  # GPIO pin for tilt servo
    
    print(f"Pan Pin:  {PAN_PIN}")
    print(f"Tilt Pin: {TILT_PIN}")
    print()
    
    try:
        controller = CameraController(pan_pin=PAN_PIN, tilt_pin=TILT_PIN)
        print("✓ Hardware initialized successfully!")
        print()
        print("Starting controller in 2 seconds...")
        print("(Press 'H' at any time for help)")
        time.sleep(2)
        
        controller.run()
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure:")
        print("  1. GPIO pins are correct")
        print("  2. Servos are connected properly")
        print("  3. You have proper permissions (try sudo)")
        sys.exit(1)


if __name__ == "__main__":
    main()
