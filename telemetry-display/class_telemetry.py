from FSM import *
from state_telemetry import *
import time
from MultiViewDisplay import MultiViewDisplay
import Jetson.GPIO as GPIO
import threading

feature = type('feature', (object,), {})  # Simple feature class for demonstration

class Telemetry(feature): 
    def __init__(self):
        self.FSM = FSM(self, debug=True)
        try:
            self.display = MultiViewDisplay()
            self.display_thread = threading.Thread(target=self.display.run, kwargs={'target_fps':10, 'live':True}, daemon=True)
            self.display_thread.start()
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        self.button = 7  # GPIO pin for button input
        self.button_held = False
        self.press_start_time = None
        
        self._initButton(pin=self.button)  # Initialize button with GPIO setup
        
        # Add States to be defined using state_template.py
        self.FSM.addState("MultiViewState", MultiViewState(self.FSM)) 
        self.FSM.addState("RGBState", RGBState(self.FSM))
        self.FSM.addState("IRState", IRState(self.FSM))     
        self.FSM.addState("GasState", GasState(self.FSM))
        
        # Set initial state
        self.FSM.setState('MultiViewState')  
        
    def execute(self):
        self.FSM.execute()  # Execute the FSM logic without packet data

    def on_press(self):
        if self.FSM.debug:
            print("Button Pressed")
        self.press_start_time = time.time()  # Start timing when button is first pressed
    
    def on_release(self):
        if self.FSM.debug:
            print("Button Released")
        duration = time.time() - self.press_start_time if self.press_start_time else 0
        self.press_start_time = None  # Reset timing on release
        if duration >= 3:  # Check if button was held for 3 seconds
            self.button_held = True
        else:
            self.button_held = False

    def button_callback(self, channel):
        if GPIO.input(channel) == GPIO.HIGH:
            self.on_press()
        else:
            self.on_release()

    def _initButton(self, pin=9):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(pin, GPIO.IN)
        GPIO.add_event_detect(pin, GPIO.BOTH, callback=self.button_callback, bouncetime=50)
