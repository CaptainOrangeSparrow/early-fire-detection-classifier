
State = type('State', (object,), {})  # Simple State class for demonstration

#====================================================================================

class transition(object):
    """
    A transition represents a possible change from one state to another in the FSM.

    @param: toState The name of the state to transition to when this transition is executed
    @param: condition A function that returns True when the transition should occur (default None, meaning the transition is always valid)
    @param: debug If True, prints debug information when the transition is executed (default False)

    """
    def __init__(self, toState, condition=None, debug=False):
        """
        initializes a transition with the specified target state, condition function, 
        and debug flag. The transition will be executed when the condition function returns 
        True (or immediately if no condition is specified), and will cause the FSM to move to
        the specified target state.
        """
        self.toState = toState
        self.condition = condition  # A function that returns True when the transition should occur
        self.debug = debug

    def isValid(self):
        """
        Evaluates the condition for this transition to determine if it is valid. If no condition
        is specified, the transition is considered valid by default.
        """
        if self.condition is None:
            return True  # If no condition is specified, the transition is always valid
        return self.condition()  # Evaluate the condition function to determine if the transition is valid
    
    def execute(self):
        """
        Executes the transition logic. In this simple implementation, there is no additional
        logic to execute beyond transitioning to the target state, but this method can be extended
        to include any necessary actions that should occur during the transition. 
        """
        if self.debug:
            print(f"Transitioning to state: {self.toState}")

#====================================================================================

#====================================================================================
# Base State class  
class State(State):
    """
    A state represents a specific condition or mode of operation in the FSM. Each state can have
    
    @param: FSM The FSM instance that this state belongs to, allowing the state to interact with the FSM and trigger transitions
    """
    
    def __init__(self, FSM):
        """
        Initializes a state with a reference to the FSM it belongs to. The state can use this 
        reference to trigger transitions and interact with the FSM as needed. Also initializes
        a name for the state (defaulting to the class name) and a dictionary to hold transitions
        from this state.
        """
        
        self.FSM = FSM
        self.name = self.__class__.__name__  # Set name to the class name by default
        self.transitions = {}  # Dictionary to hold transitions from this state
    
    def enter(self):
        """
        Enter handles setup and initialization when the state is entered. This method can be
        overridden by specific states to implement custom behavior that should occur when the
        state is entered. It cannot transition to another state directly (do not use toTransition 
        in this method), but can set up conditions for transitions to be evaluated in the execute method.
        """
        if self.FSM.debug:  
            print(f"Entering state: {self.name}")
    
    def execute(self):
        """
        Execute contains the main logic for the state and is called repeatedly while the FSM 
        is in this state. This method can be overridden by specific states to implement the 
        behavior that should occur while the FSM is in this state. It can also evaluate 
        conditions and call toTransition to move to another state when needed. This method
        also sets up conditions for transitions to be evaluated, allowing the FSM to move 
        to other states based on the logic implemented here.
        """
        if self.FSM.debug:
            print(f"Executing state: {self.name}")
    

    def exit(self):
        """
        Exit handles cleanup and any necessary teardown when the state is exited. This method
        can be overridden by specific states to implement custom behavior that should occur 
        when the state is exited. It cannot transition to another state directly (do not use 
        toTransition in this method), nor can it set up conditions for transitions to be 
        evaluated in the execute method, as it is only responsible for cleanup when exitin
        the state.
        """
        if self.FSM.debug:
            print(f"Exiting state: {self.name}")
        
    def addTransition(self, transName, transitionObj):
        """
        Adds a transition to this state. The transition is identified by a name (transName)
        and is represented by a transition object (transitionObj) that contains the logic for
        transitioning to another state.
        
        @param: transName The name of the transition, used to identify it when triggering transitions
        @param: transitionObj The transition object that contains the logic for transitioning to another state
        """
        self.transitions[transName] = transitionObj
    
    def toTransition(self, transName):
        """
        Triggers a transition from this state to another state based on the specified name of 
        the transition. This method looks up the transition by name in the transitions dictionary
        and calls the FSM's toTransition method to set the current transition in the FSM. The 
        actual execution of the transition will occur in the FSM's execute method, which will 
        evaluate the transition's condition and perform the state change if the transition is valid.
        
        @param: transName The name of the transition to trigger, which should correspond to a key in the transitions dictionary
        """
        if transName in self.transitions:
            self.FSM.toTransition(transName)
        else:
            raise KeyError(f"Transition '{transName}' not found in state '{self.name}'.")
    
#====================================================================================



#====================================================================================
class FSM(object):
    """
    FSM (Finite State Machine) manages the states and transitions of the system. It keeps track
    of the current state, allows adding states and transitions, and executes the logic for 
    transitioning between states based on defined conditions.
    
    @param: container A reference to the container object that holds the FSM, allowing states and transitions to interact with the broader system
    @param: debug If True, prints debug information about state changes and transitions (default False)
    """
    def __init__(self, container, debug=False):
        """
        Initializes the FSM with a reference to the container object and an optional debug flag. 
        The FSM starts with no states, no current state, and no active transition. The container
        is responsible for managing the FSM and providing any necessary context or resources that
        states and transitions may need to operate effectively. The debug flag enables printing of
        debug information to help trace the flow of state changes and transitions during execution.
        """
        self.container = container
        self.states = {}
        self.curState = None
        self.prevState = None
        self.trans = None
        self.debug = debug
        
    def setState(self, stateName):
        """
        Sets the current state of the FSM to the specified state name. This method looks up the 
        state by name in the states dictionary and updates the current state. It also keeps track 
        of the previous state. If the specified state name is not found in the states dictionary,
        it raises a KeyError.
        
        @param: stateName The name of the state to set as the current state, which should correspond to a key in the states dictionary
        """
        self.prevState = self.curState
        try:
            self.curState = self.states[stateName]
        except KeyError:
            raise KeyError(f"State '{stateName}' not found in FSM.")
        if self.debug:
            print(f"Current state set to: {self.curState.name}")
    
    def addState(self, stateName, stateObj):
        """
        Adds a state to the FSM. The state is identified by a name (stateName) and is represented
        by a state object (stateObj) that contains the logic for that state. The state is added to
        the FSM's states dictionary.
        
        @param: stateName The name of the state, used to identify it when setting the current state
        @param: stateObj The state object that contains the logic for that state
        """
        self.states[stateName] = stateObj
        if self.debug:
            print(f"Added state: {stateName}")
            
    def toTransition(self, transName):
        """
        Updates the current transition in the FSM to the specified transition name. This method
        looks up the transition by name in the current state's transitions dictionary and sets 
        it as the active transition in the FSM. The actual execution of the transition will 
        occur in the FSM's execute method, which will evaluate the transition's condition 
        and perform the state change if the transition is valid. If the specified transition.
        
        @transName The name of the transition to set as the current transition, which should correspond to a key in the current state's transitions dictionary
        """
        if transName in self.curState.transitions:
            self.trans = self.curState.transitions[transName]
        else:
            raise KeyError(f"Transition '{transName}' not found in current state '{self.curState.name}'.")
        if self.debug:
            print(f"Current transition set to: {transName}")
            
    def execute(self):
        """
        Main execution loop for the FSM. This method should be called repeatedly (e.g., in a main loop)
        to allow the FSM to evaluate transitions and execute the logic of the current state. It first 
        checks if there is an active transition and if it is valid. If the transition is valid, it 
        executes the transition logic, updates the current state, and calls the enter method of the
        new state. After handling any transitions, it calls the execute method of the current state
        to perform its logic.
        """
        if self.trans:
            if self.trans.isValid():
                self.curState.exit()  # Exit current state before transitioning
                self.trans.execute() # Execute the transition logic
                self.setState(self.trans.toState)
                self.curState.enter()  # Enter new state after transitioning
            self.trans = None  # Reset transition after execution
        self.curState.execute()
            
#====================================================================================

        
        
