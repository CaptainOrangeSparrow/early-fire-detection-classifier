#!/usr/bin/env python3
"""
Comprehensive Servo Test Suite
Tests various movement patterns, transition types, and speeds
for the 2-axis camera mount servo system.
"""

import CameraMount2Axis
import time
import sys

# Jetson Nano BOARD pins with PWM support
PAN_PIN = 33
TILT_PIN = 32

def print_test(test_name):
    """Print formatted test header"""
    print("\n" + "="*60)
    print(f"TEST: {test_name}")
    print("="*60)

def test_basic_movements(mount):
    """Test basic positioning without transitions"""
    print_test("Basic Movements (Instant Transitions)")
    
    positions = [
        (90, 90, "Center"),
        (0, 90, "Far Left"),
        (180, 90, "Far Right"),
        (90, 0, "Full Down"),
        (90, 180, "Full Up"),
        (0, 0, "Bottom Left Corner"),
        (180, 180, "Top Right Corner"),
        (180, 0, "Bottom Right Corner"),
        (0, 180, "Top Left Corner"),
        (90, 90, "Return to Center")
    ]
    
    for pan, tilt, description in positions:
        print(f"  → {description}: Pan={pan}°, Tilt={tilt}°")
        mount.set_position(pan, tilt)
        time.sleep(1.5)

def test_linear_transitions(mount):
    """Test linear transition movements at various speeds"""
    print_test("Linear Transitions - Different Speeds")
    
    mount.center()
    time.sleep(1)
    
    # Test different speeds
    speeds = [2.0, 5.0, 10.0]
    
    for speed in speeds:
        print(f"\n  Speed: {speed} deg/tick")
        
        # Set transition type and speed
        mount.pan.set_angle(90, transition_type='linear', speed=speed)
        mount.tilt.set_angle(90, transition_type='linear', speed=speed)
        time.sleep(0.5)
        
        # Sweep left to right
        print(f"    → Sweeping pan left to right at speed {speed}")
        mount.pan.set_angle(0, transition_type='linear', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(180, transition_type='linear', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(90, transition_type='linear', speed=speed)
        time.sleep(2)

def test_s_curve_transitions(mount):
    """Test S-curve (sigmoid) transitions"""
    print_test("S-Curve Transitions (Smooth Acceleration/Deceleration)")
    
    mount.center()
    time.sleep(1)
    
    speeds = [3.0, 7.0, 9.0]
    
    for speed in speeds:
        print(f"\n  Speed: {speed} deg/tick")
        
        # Diagonal movement with S-curve
        print(f"    → Diagonal sweep (s-curve)")
        mount.pan.set_angle(0, transition_type='s-curve', speed=speed)
        mount.tilt.set_angle(0, transition_type='s-curve', speed=speed)
        time.sleep(4)
        
        mount.pan.set_angle(180, transition_type='s-curve', speed=speed)
        mount.tilt.set_angle(180, transition_type='s-curve', speed=speed)
        time.sleep(4)
        
        mount.pan.set_angle(0, transition_type='s-curve', speed=speed)
        mount.tilt.set_angle(0, transition_type='s-curve', speed=speed)
        
        mount.pan.set_angle(90, transition_type='s-curve', speed=speed)
        mount.tilt.set_angle(90, transition_type='s-curve', speed=speed)
        time.sleep(4)


        mount.center()
        time.sleep(3)

def test_ease_out_quad(mount):
    """Test ease-out quadratic transitions"""
    print_test("Ease-Out Quadratic Transitions (Fast Start, Slow End)")
    
    mount.center()
    time.sleep(1)
    
    speeds = [4.0, 5.0, 7.0, 9.0]
    
    for speed in speeds:
        print(f"\n  Speed: {speed} deg/tick")
        
        print(f"    → Full sweep with ease-out")
        mount.pan.set_angle(0, transition_type='ease-out-quad', speed=speed)
        mount.tilt.set_angle(0, transition_type='ease-out-quad', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(180, transition_type='ease-out-quad', speed=speed)
        mount.tilt.set_angle(180, transition_type='ease-out-quad', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(90, transition_type='ease-out-quad', speed=speed)
        mount.tilt.set_angle(90, transition_type='ease-out-quad', speed=speed)
        time.sleep(2)

def test_ease_in_out_quad(mount):
    """Test ease-in-out quadratic transitions"""
    print_test("Ease-In-Out Quadratic Transitions (Slow Start, Fast Middle, Slow End)")
    
    mount.center()
    time.sleep(1)
    
    speeds = [3.0, 5.0, 7.0]
    
    for speed in speeds:
        print(f"\n  Speed: {speed} deg/tick")
        
        print(f"    → Full sweep with ease-in-out")
        mount.pan.set_angle(0, transition_type='ease-in-out-quad', speed=speed)
        mount.tilt.set_angle(0, transition_type='ease-in-out-quad', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(180, transition_type='ease-in-out-quad', speed=speed)
        mount.tilt.set_angle(180, transition_type='ease-in-out-quad', speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(90, transition_type='ease-in-out-quad', speed=speed)
        mount.tilt.set_angle(90, transition_type='ease-in-out-quad', speed=speed)
        time.sleep(2)

def test_sine_transitions(mount):
    """Test sine easing transitions"""
    print_test("Sine Easing Transitions (Very Smooth)")
    
    mount.center()
    time.sleep(1)
    
    speeds = [3.0, 5.0, 7.0]
    
    for speed in speeds:
        print(f"\n  Speed: {speed} deg/tick")
        
        print(f"    → Diagonal sweep with sine easing")
        mount.pan.set_angle(0, transition_type='sine', speed=speed)
        mount.tilt.set_angle(0, transition_type='sine', speed=speed)
        time.sleep(4)
        
        mount.pan.set_angle(180, transition_type='sine', speed=speed)
        mount.tilt.set_angle(180, transition_type='sine', speed=speed)
        time.sleep(4)
        
        mount.pan.set_angle(90, transition_type='sine', speed=speed)
        mount.tilt.set_angle(90, transition_type='sine', speed=speed)
        time.sleep(3)

def test_transition_comparison(mount):
    """Compare all transition types side-by-side"""
    print_test("Transition Type Comparison (Same Speed)")
    
    speed = 2.0
    transitions = ['instant', 'linear', 's-curve', 'ease-out-quad', 'ease-in-out-quad', 'sine']
    
    for trans_type in transitions:
        print(f"\n  Transition Type: {trans_type}")
        
        # Reset to center
        mount.pan.set_angle(90, transition_type='instant')
        mount.tilt.set_angle(90, transition_type='instant')
        time.sleep(1)
        
        # Execute same movement with different transition
        print(f"    → Pan sweep 0° to 180°")
        mount.pan.set_angle(0, transition_type=trans_type, speed=speed)
        time.sleep(3)
        
        mount.pan.set_angle(180, transition_type=trans_type, speed=speed)
        time.sleep(3)
        
        print(f"    → Return to center")
        mount.pan.set_angle(90, transition_type=trans_type, speed=speed)
        time.sleep(2)

def test_pattern_movements(mount):
    """Test complex movement patterns"""
    print_test("Pattern Movements")
    
    # Square pattern
    print("\n  Pattern: Square (linear transitions)")
    mount.center()
    time.sleep(1)
    
    corners = [(45, 45), (135, 45), (135, 135), (45, 135), (90, 90)]
    for i, (pan, tilt) in enumerate(corners):
        print(f"    → Corner {i+1}: Pan={pan}°, Tilt={tilt}°")
        mount.pan.set_angle(pan, transition_type='linear', speed=3.0)
        mount.tilt.set_angle(tilt, transition_type='linear', speed=3.0)
        time.sleep(2)
    
    # Diagonal scan pattern with sine easing
    print("\n  Pattern: Diagonal Scan (sine easing)")
    scan_positions = [
        (30, 150), (150, 30), (30, 150), (150, 30), (90, 90)
    ]
    for i, (pan, tilt) in enumerate(scan_positions):
        print(f"    → Scan position {i+1}: Pan={pan}°, Tilt={tilt}°")
        mount.pan.set_angle(pan, transition_type='sine', speed=4.0)
        mount.tilt.set_angle(tilt, transition_type='sine', speed=4.0)
        time.sleep(3)
    
    # Figure-8 approximation with ease-in-out
    print("\n  Pattern: Figure-8 Approximation (ease-in-out)")
    figure8 = [
        (90, 90), (60, 120), (90, 150), (120, 120), 
        (90, 90), (120, 60), (90, 30), (60, 60), (90, 90)
    ]
    for i, (pan, tilt) in enumerate(figure8):
        print(f"    → Point {i+1}: Pan={pan}°, Tilt={tilt}°")
        mount.pan.set_angle(pan, transition_type='ease-in-out-quad', speed=2.0)
        mount.tilt.set_angle(tilt, transition_type='ease-in-out-quad', speed=2.0)
        time.sleep(1.5)

def test_stress_rapid_changes(mount):
    """Test rapid direction changes and interruptions"""
    print_test("Stress Test: Rapid Direction Changes")
    
    mount.center()
    time.sleep(1)
    
    print("\n  Rapidly changing targets (testing interruption handling)")
    rapid_targets = [0, 180, 45, 135, 90, 60, 120, 30, 150, 90]
    
    for i, target in enumerate(rapid_targets):
        print(f"    → Target {i+1}: {target}°", end='\r')
        mount.pan.set_angle(target, transition_type='linear', speed=5.0)
        time.sleep(0.3)  # Short delay before changing target
    
    print("\n  Waiting for final position...")
    time.sleep(2)

def test_simultaneous_movements(mount):
    """Test coordinated pan and tilt movements"""
    print_test("Simultaneous Pan and Tilt Movements")
    
    mount.center()
    time.sleep(1)
    
    movements = [
        ((0, 0), "Bottom-Left", 'linear', 2.0),
        ((180, 180), "Top-Right", 's-curve', 3.0),
        ((180, 0), "Bottom-Right", 'ease-out-quad', 2.5),
        ((0, 180), "Top-Left", 'ease-in-out-quad', 3.0),
        ((90, 90), "Center", 'sine', 2.0)
    ]
    
    for (pan, tilt), desc, trans_type, speed in movements:
        print(f"\n  → Moving to {desc} (Pan={pan}°, Tilt={tilt}°)")
        print(f"    Transition: {trans_type}, Speed: {speed}")
        mount.pan.set_angle(pan, transition_type=trans_type, speed=speed)
        mount.tilt.set_angle(tilt, transition_type=trans_type, speed=speed)
        time.sleep(4)

def test_edge_cases(mount):
    """Test edge cases and boundary conditions"""
    print_test("Edge Cases and Boundary Conditions")
    
    print("\n  Testing angle limits (should clamp to 0-180)")
    mount.pan.set_angle(-10, transition_type='instant')
    mount.tilt.set_angle(-10, transition_type='instant')
    time.sleep(1)
    print("    → Set to -10° (should be at 0°)")
    
    mount.pan.set_angle(200, transition_type='instant')
    mount.tilt.set_angle(200, transition_type='instant')
    time.sleep(1)
    print("    → Set to 200° (should be at 180°)")
    
    mount.center()
    time.sleep(1)
    print("    → Returned to center")
    
    print("\n  Testing very slow speed")
    mount.pan.set_angle(45, transition_type='linear', speed=0.1)
    time.sleep(3)
    print("    → Moving at speed=0.1 (very slow)")
    
    print("\n  Testing very fast speed")
    mount.pan.set_angle(135, transition_type='linear', speed=20.0)
    time.sleep(2)
    print("    → Moving at speed=20.0 (very fast)")
    
    mount.center()
    time.sleep(1)

def run_all_tests(mount):
    """Run all test suites"""
    print("\n" + "="*60)
    print("SERVO COMPREHENSIVE TEST SUITE")
    print("="*60)
    print("\nThis test will run multiple test suites to verify")
    print("all servo functionality and transition types.")
    print("\nPress Ctrl+C at any time to stop the tests.")
    print("="*60)
    
    time.sleep(2)
    
    try:
        test_basic_movements(mount)
        test_linear_transitions(mount)
        test_s_curve_transitions(mount)
        test_ease_out_quad(mount)
        test_ease_in_out_quad(mount)
        test_sine_transitions(mount)
        test_transition_comparison(mount)
        test_pattern_movements(mount)
        test_simultaneous_movements(mount)
        test_stress_rapid_changes(mount)
        test_edge_cases(mount)
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("TESTS INTERRUPTED BY USER")
        print("="*60)
    except Exception as e:
        print("\n\n" + "="*60)
        print(f"ERROR DURING TESTING: {e}")
        print("="*60)
        raise

def main():
    print("\nInitializing 2-Axis Camera Mount...")
    mount = CameraMount2Axis.CameraMount2Axis(PAN_PIN, TILT_PIN)
    
    try:
        # Option to run specific tests
        if len(sys.argv) > 1:
            test_name = sys.argv[1].lower()
            
            test_map = {
                'basic': test_basic_movements,
                'linear': test_linear_transitions,
                's-curve': test_s_curve_transitions,
                'ease-out': test_ease_out_quad,
                'ease-in-out': test_ease_in_out_quad,
                'sine': test_sine_transitions,
                'compare': test_transition_comparison,
                'patterns': test_pattern_movements,
                'simultaneous': test_simultaneous_movements,
                'stress': test_stress_rapid_changes,
                'edge': test_edge_cases,
                'all': run_all_tests
            }
            
            if test_name in test_map:
                if test_name == 'all':
                    run_all_tests(mount)
                else:
                    test_map[test_name](mount)
            else:
                print(f"Unknown test: {test_name}")
                print(f"Available tests: {', '.join(test_map.keys())}")
        else:
            # Run all tests by default
            run_all_tests(mount)
            
    finally:
        print("\nShutting down servos...")
        mount.shutdown()
        print("Cleanup complete.\n")

if __name__ == "__main__":
    main()
