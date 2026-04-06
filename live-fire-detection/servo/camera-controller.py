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
            transition_speed=2.0,
            pan_limits=(0.0, 180.0),
            tilt_limits=(0.0, 135)
        )

        self.increment = 5.0
        self.transition_speed = 2.0
        self.transition_type = 'linear'

        self.transition_types = [
            'instant',
            'linear',
            's-curve',
            'ease-out-quad',
            'ease-in-out-quad',
            'sine'
        ]

        self.saved_positions = {
            '1': (50, 102.5),
            '2': (45, 135),
            '3': (135, 135),
            '4': (90, 100),
            '5': (90, 170),
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

        print(f"📍 Position:")
        print(f"   Pan:  {self.camera.pan.get_angle():6.1f}°, (duty: {self.camera.pan.current_duty:.2f}%)")
        print(f"   Tilt: {self.camera.tilt.get_angle():6.1f}°, (duty: {self.camera.tilt.current_duty:.2f}%)")
        print()

        print(f"⚙️  Settings:")
        print(f"   Transition: {self.transition_type}")
        print(f"   Speed:      {self.transition_speed:.1f}°/step")
        print(f"   Increment:  {self.increment:.1f}°")
        print(f"   Limits:     Pan({self.camera.pan.min_limit:.0f}-{self.camera.pan.max_limit:.0f}), "
              f"Tilt({self.camera.tilt.min_limit:.0f}-{self.camera.tilt.max_limit:.0f})")
        print()

        print(f"💬 Last: {self.last_command}")
        print()

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
        print("  L           → Adjust Tilt Limits")
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

        if key in ['a', 'A', '\x1b[D']:  # Left
            new_pan = max(self.camera.pan.min_limit, current_pan - self.increment)
            self.camera.set_pan(new_pan)
            self.last_command = f"Pan left to {new_pan:.1f}°"

        elif key in ['d', 'D', '\x1b[C']:  # Right
            new_pan = min(self.camera.pan.max_limit, current_pan + self.increment)
            self.camera.set_pan(new_pan)
            self.last_command = f"Pan right to {new_pan:.1f}°"

        elif key in ['w', 'W', '\x1b[A']:  # Up
            new_tilt = max(self.camera.tilt.min_limit, current_tilt - self.increment)
            self.camera.set_tilt(new_tilt)
            self.last_command = f"Tilt up to {new_tilt:.1f}°"

        elif key in ['s', 'S', '\x1b[B']:  # Down
            new_tilt = min(self.camera.tilt.max_limit, current_tilt + self.increment)
            self.camera.set_tilt(new_tilt)
            self.last_command = f"Tilt down to {new_tilt:.1f}°"

    def handle_increment(self, key):
        """Handle increment adjustment"""
        if key == '+' or key == '=':
            self.increment = min(180.0, self.increment + 1.0)
            self.last_command = f"Increment increased to {self.increment:.1f}°"
        elif key == '-' or key == '_':
            self.increment = max(0.25, self.increment - 1.0)
            self.last_command = f"Increment decreased to {self.increment:.1f}°"

    def handle_speed(self, key):
        """Handle speed adjustment"""
        if key == ']':
            self.transition_speed = min(30.0, self.transition_speed + 0.05)
            self.camera.pan.transition_speed = self.transition_speed
            self.camera.tilt.transition_speed = self.transition_speed
            self.last_command = f"Speed increased to {self.transition_speed:.1f}°/step"
        elif key == '[':
            self.transition_speed = max(0.05, self.transition_speed - 0.05)
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

    def set_tilt_limits(self):
        """Interactive tilt limit adjustment"""
        self._clear_screen()
        print("=" * 70)
        print("  SET TILT LIMITS")
        print("=" * 70)
        print(f"Current Limits: {self.camera.tilt.min_limit:.1f}° to {self.camera.tilt.max_limit:.1f}°")
        print()

        min_in = self._get_input("Enter new MIN tilt angle (e.g. 90): ")
        if min_in is None: return
        max_in = self._get_input("Enter new MAX tilt angle (e.g. 180): ")
        if max_in is None: return

        try:
            new_min = float(min_in)
            new_max = float(max_in)

            if new_min < new_max:
                self.camera.set_limits(tilt_limits=(new_min, new_max))
                self.last_command = f"Tilt limits updated: {new_min}-{new_max}"
            else:
                self.last_command = "Error: Min must be less than Max"
        except ValueError:
            self.last_command = "Invalid input"

    def goto_position(self):
        """Go to specific angles"""
        self._clear_screen()
        print("=" * 70)
        print("  GO TO POSITION")
        print("=" * 70)
        print()

        pan_input = self._get_input(
            f"Enter Pan angle ({self.camera.pan.min_limit:.0f}-{self.camera.pan.max_limit:.0f}): "
        )
        if pan_input is None:
            self.last_command = "Go to cancelled"
            return

        tilt_input = self._get_input(
            f"Enter Tilt angle ({self.camera.tilt.min_limit:.0f}-{self.camera.tilt.max_limit:.0f}): "
        )
        if tilt_input is None:
            self.last_command = "Go to cancelled"
            return

        try:
            pan = float(pan_input)
            tilt = float(tilt_input)
            self.camera.set_position(pan, tilt)
            self.last_command = f"Moving to Pan={pan:.1f}°, Tilt={tilt:.1f}°"
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
        print("SETTINGS:")
        print("  +/-          - Increase/decrease step increment")
        print("  [/]          - Decrease/increase transition speed")
        print("  T            - Change transition type")
        print("  G            - Go to specific angles")
        print("  P            - Save current position to preset")
        print("  L            - Adjust Tilt Limits (Safety Stop)")
        print()
        print("PRESETS:")
        print("  1-5          - Load saved preset positions")
        print("  C            - Center position (90°, 90°)")
        print()
        print("  Q / ESC      - Quit program")
        print()

        self._get_input("Press Enter to continue...")
        self.last_command = "Help displayed"

    def run(self):
        """Main control loop"""
        self._refresh_display()

        try:
            while self.running:
                key = self._get_key()

                if key in ['w', 'W', 'a', 'A', 's', 'S', 'd', 'D',
                           '\x1b[A', '\x1b[B', '\x1b[C', '\x1b[D']:
                    self.handle_wasd(key)
                    self._refresh_display()

                elif key in ['c', 'C']:
                    self.camera.center()
                    self.last_command = "Centered to 90°, 90°"
                    self._refresh_display()

                elif key in ['1', '2', '3', '4', '5']:
                    self.load_preset(key)
                    self._refresh_display()

                elif key in ['+', '=', '-', '_']:
                    self.handle_increment(key)
                    self._refresh_display()

                elif key in ['[', ']', '{', '}']:
                    self.handle_speed(key)
                    self._refresh_display()

                elif key in ['t', 'T']:
                    self.change_transition_type()
                    self._refresh_display()

                elif key in ['g', 'G']:
                    self.goto_position()
                    self._refresh_display()

                elif key in ['p', 'P']:
                    self.save_position()
                    self._refresh_display()

                elif key in ['l', 'L']:
                    self.set_tilt_limits()
                    self._refresh_display()

                elif key in ['h', 'H']:
                    self.show_help()
                    self._refresh_display()

                elif key in ['q', 'Q', '\x1b']:
                    self.last_command = "Shutting down..."
                    self._refresh_display()
                    self.running = False
                    break

                time.sleep(0.01)

        except KeyboardInterrupt:
            pass
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

    PAN_PIN = 33
    TILT_PIN = 32

    print(f"Pan Pin:  {PAN_PIN}")
    print(f"Tilt Pin: {TILT_PIN}")
    print("Note: Tilt is clamped to 0-135 degrees by default.")
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
        sys.exit(1)


if __name__ == "__main__":
    main()
