from FSM import *

#====================================================================================
# Example of a specific state that inherits from the base State class
class MultiViewState(State):
    def __init__(self, FSM):
        super(MultiViewState, self).__init__(FSM)
        self.addTransition('toRGBState', transition('RGBState', condition=self.wasHeld, debug=self.FSM.debug))
        self.packetReceived = False
        
    def enter(self):
        if self.FSM.debug:
            print(f"Entering MultiViewState: {self.name}")
            
        self.FSM.container.display.request_view("MultiView")  # Set the display to MultiView when entering this state
       #super(AwaitPacketState, self).enter() # Call the base class enter method if needed for additional setup
        
    def execute(self):
        # Transition to RGBState if the button was held for 3 seconds
        if self.wasHeld():
            self.toTransition('toRGBState') 
     
    def exit(self):
        if self.FSM.debug:
            print(f"Exiting MultiViewState: {self.name}")
        self.FSM.container.button_held = False  # Reset button held state on exit
                    
    def wasHeld(self):
        return self.FSM.container.button_held
#====================================================================================

#====================================================================================
# Example of a specific state that inherits from the base State class
class RGBState(State):
    def __init__(self, FSM):
        super(RGBState, self).__init__(FSM)
        self.addTransition('toIRState', transition('IRState', condition=self.wasHeld, debug=self.FSM.debug))
        
    def enter(self):
        if self.FSM.debug:
            print(f"Entering RGBState: {self.name}")
        self.FSM.container.display.request_view("RGB")  # Set the display to RGB when entering this state
       #super(AwaitPacketState, self).enter() # Call the base class enter method if needed for additional setup
        
    def execute(self):
        if self.wasHeld():
            self.toTransition('toIRState') # Transition to RGBState after processing the packet
     
    
    def exit(self):
        if self.FSM.debug:
            print(f"Exiting RGBState: {self.name}")
        self.FSM.container.button_held = False  # Reset button held state on exit
                    
    def wasHeld(self):
        return self.FSM.container.button_held
#====================================================================================

#====================================================================================
# Example of a specific state that inherits from the base State class
class IRState(State):
    def __init__(self, FSM):
        super(IRState, self).__init__(FSM)
        self.addTransition('toGasState', transition('GasState', condition=self.wasHeld, debug=self.FSM.debug))
        
    def enter(self):
        if self.FSM.debug:
            print(f"Entering IRState: {self.name}")
        self.FSM.container.display.request_view("IR")  # Set the display to IR when entering this state
       #super(AwaitPacketState, self).enter() # Call the base class enter method if needed for additional setup
        
    def execute(self):
        if self.wasHeld():
            self.toTransition('toGasState') # Transition to IRState after processing the packet 
    
    def exit(self):
        if self.FSM.debug:
            print(f"Exiting IRState: {self.name}")
        self.FSM.container.button_held = False  # Reset button held state on exit
                    
    def wasHeld(self):
        return self.FSM.container.button_held
#====================================================================================

#====================================================================================
# Example of a specific state that inherits from the base State class
class GasState(State):
    def __init__(self, FSM):
        super(GasState, self).__init__(FSM)
        self.addTransition('toMultiViewState', transition('MultiViewState', condition=self.wasHeld, debug=self.FSM.debug))
        
    def enter(self):
        if self.FSM.debug:
            print(f"Entering GasState: {self.name}")
        #super(AwaitPacketState, self).enter() # Call the base class enter method if needed for additional setup
        self.FSM.container.display.request_view("Gas")  # Set the display to Gas when entering this state
        
    def execute(self):
        if self.wasHeld():
            self.toTransition('toMultiViewState') # Transition to GasState after processing the packet    
    
    def exit(self):
        if self.FSM.debug:
            print(f"Exiting GasState: {self.name}")
        self.FSM.container.button_held = False  # Reset button held state on exit
                    
    def wasHeld(self):
        return self.FSM.container.button_held
#====================================================================================