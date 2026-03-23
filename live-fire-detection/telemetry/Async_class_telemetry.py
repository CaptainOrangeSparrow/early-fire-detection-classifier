from telemetry.FSM import *
from telemetry.Async_state_telemetry import *
import time
from telemetry.AsyncMultiViewDisplay import MultiViewDisplay
import Jetson.GPIO as GPIO
from telemetry.http_stream import HTTPStreamServer
import threading
import time
import asyncio

feature = type('feature', (object,), {})  # Simple feature class for demonstration

class Telemetry(feature): 
    def __init__(self, auto_switch: float | int = None, stream: bool = False, debug: bool = False, rgb_cam=None, ir_cam=None, adc_module=None):   
        self.debug = debug

        self.display: MultiViewDisplay = MultiViewDisplay(preview=False, debug=self.debug, rgb_cam=rgb_cam, ir_cam=ir_cam, adc_module=adc_module)
        
        self.stream = stream
        if self.stream:
            self.http_stream = HTTPStreamServer(self.display)
            self.http_stream.start()
        
        self.FSM: FSM = FSM(self, debug=self.debug)
        
        self.button = 7  # GPIO pin for button input
        self.button_held = False
        self.press_start_time = None
        self.auto_switch = auto_switch


        self._initButton(pin=self.button)  # Initialize button with GPIO setup
        if isinstance(auto_switch,(int,float)):
            self._initAutoSwitch(idleTime=auto_switch)
        
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
        if self.debug:
            print("Button Pressed")
        self.press_start_time = time.time()  # Start timing when button is first pressed
    
    def on_release(self):
        if self.debug:
            print("Button Released")
        duration = time.time() - self.press_start_time if self.press_start_time else 0
        self.press_start_time = None  # Reset timing on release
        if duration >= 2:  # Check if button was held for 3 seconds
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
    # Auto-Switch support
    # ----------------------------

    def _switch_thread(self, idleTime):
        while True:
            time.sleep(idleTime)
            self.button_held = True
            if self.debug:
                print("Switch")
            
                
    def _initAutoSwitch(self,idleTime=5):
        t = threading.Thread(target=self._switch_thread, args=[idleTime], daemon=True)
        t.start()
