from FSM import *
from Async_state_telemetry import *
import time
from AsyncMultiViewDisplay import MultiViewDisplay
import Jetson.GPIO as GPIO
from http_stream import HTTPStreamServer
import threading
import time
import asyncio

feature = type('feature', (object,), {})  # Simple feature class for demonstration

class Telemetry(feature): 
    def __init__(self):        
        self.display: MultiViewDisplay = MultiViewDisplay(preview=False)
        
        self.http_stream = HTTPStreamServer(self.display)
        self.http_stream.start()
        
        self.FSM: FSM = FSM(self, debug=True)
        
        self.button = 7  # GPIO pin for button input
        self.button_held = False
        self.press_start_time = None
        
        self._initButton(pin=self.button)  # Initialize button with GPIO setup
        self._initAutoSwitch()
        
        # Add States to be defined using state_template.py
        self.FSM.addState("MultiViewState", MultiViewState(self.FSM)) 
        self.FSM.addState("RGBState", RGBState(self.FSM))
        self.FSM.addState("IRState", IRState(self.FSM))     
        self.FSM.addState("GasState", GasState(self.FSM))
        
        # Set initial state
        self.FSM.setState('MultiViewState')  
            
    async def fsm_task(self):

        while True:
            self.FSM.execute()      # runs self.FSM.execute()
            await asyncio.sleep(0.02)   # ~50 Hz control loop
        
    async def execute(self):
        await asyncio.gather(
            self.display.run(),
            self.fsm_task()
        )

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

    def _initButton(self, pin=7):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(pin, GPIO.IN)
        GPIO.add_event_detect(pin, GPIO.BOTH, callback=self.button_callback, bouncetime=50)

    # ----------------------------
    # Keyboard spacebar support
    # ----------------------------

    def _switch_thread(self):
        while True:
            time.sleep(3)
            self.button_held = True
            print("Switch")
            
                
    def _initAutoSwitch(self):
        t = threading.Thread(target=self._switch_thread, daemon=True)
        t.start()