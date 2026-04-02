import CameraMount2Axis as cm
import sys
import tty
import termios
import time

def get_key():
    """Get a single keypress from the user without requiring Enter"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def clamp_angle(angle, min_angle=0, max_angle=180):
    """Ensure angle stays within servo limits"""
    return max(min_angle, min(max_angle, angle))

if __name__ == "__main__":
    # Jetson Nano BOARD pins with PWM support
    PAN_PIN = 33
    TILT_PIN = 32
    
    # Get increment from user
    print("Enter angle increment (degrees per keypress): ", end='', flush=True)
    increment = float(input())
    
    # Initialize mount
    mount = cm.CameraMount2Axis(PAN_PIN, TILT_PIN)
    
    # Starting position
    pan_angle = 0
    tilt_angle = 0

    # Max Angle
    max_ang = 180    
    mount.set_position(pan_angle, tilt_angle)
    time.sleep(5)
    print(f"\nStarting position - Pan: {pan_angle}°, Tilt: {tilt_angle}°")
    print("\nControls:")
    print("  W - Tilt Up")
    print("  S - Tilt Down")
    print("  A - Pan Left")
    print("  D - Pan Right")
    print("  Q - Quit")
    print("\nReady! Press keys to control servos...\n")
    

    try:
        while True:
            key = get_key().lower()
            
            if key == 'q':
                print("\nExiting...")
                break
            elif key == 'w':
                tilt_angle = clamp_angle(tilt_angle + increment, max_angle=max_ang)
                mount.set_position(pan_angle, tilt_angle)
                print(f"Tilt UP   → Pan: {pan_angle}°, Tilt: {tilt_angle}°")
            elif key == 's':
                tilt_angle = clamp_angle(tilt_angle - increment, max_angle=max_ang)
                mount.set_position(pan_angle, tilt_angle)
                print(f"Tilt DOWN → Pan: {pan_angle}°, Tilt: {tilt_angle}°")
            elif key == 'a':
                pan_angle = clamp_angle(pan_angle - increment, max_angle=max_ang)
                mount.set_position(pan_angle, tilt_angle)
                print(f"Pan LEFT  → Pan: {pan_angle}°, Tilt: {tilt_angle}°")
            elif key == 'd':
                pan_angle = clamp_angle(pan_angle + increment, max_angle=max_ang)
                mount.set_position(pan_angle, tilt_angle)
                print(f"Pan RIGHT → Pan: {pan_angle}°, Tilt: {tilt_angle}°")
            elif key == '\x03':  # Ctrl+C
                break
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        print(f"Final position - Pan: {pan_angle}°, Tilt: {tilt_angle}°")
        mount.shutdown()
