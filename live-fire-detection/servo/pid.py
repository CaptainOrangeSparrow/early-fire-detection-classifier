import time
from collections import deque


class PID:
    """
    Tuning order:
        1. Set kI = kD = 0. Raise kP until the mount oscillates.
           Then halve kP.
        2. Raise kI until drift is eliminated.
        3. Raise kD until overshoot is damped.
    """

    def __init__(self, kP: float = 1.0, kI: float = 0.0, kD: float = 0.0, minOutput: float = -180.0, maxOutput: float = 180.0):
        self.kP = kP
        self.kI = kI
        self.kD = kD
        self.k1 = self.kP + self.kI + self.kD
        self.k2 = -self.kP - (2 * self.kD)
        self.k3 = self.kD
        self.minOutput = minOutput
        self.maxOutput = maxOutput


    def initialize(self, difference_equation: bool = False):
        if not difference_equation: 
            # Reset states for new tracking target
            self.currTime  = time.time()
            self.prevTime  = self.currTime
            self.prevError = 0.0

            # Term accumulators
            self.cP = 0.0
            self.cI = 0.0
            self.cD = 0.0
        else: 
            self.prevError = deque([0.0, 0.0], maxlen=2) # for difference equation method, we need to keep track of the last two errors
            self.prevUpdate = 0.0



    def update(self, error: float, difference_equation: bool = False) -> float:
        """
        Compute the PID correction for the current normalised error.

        error: Tracking Error in degrees 

        Returns:
            Angle delta in degrees to add to the current servo angle.
        """
        if not difference_equation:
            self.currTime = time.time()
            deltaTime     = self.currTime - self.prevTime
            deltaError    = error - self.prevError

            # Proportional — present error
            self.cP = error

            # Integral — accumulated error over time
            self.cI += error * deltaTime

            # Derivative — rate of change
            self.cD = (deltaError / deltaTime) if deltaTime > 0.0 else 0.0

            # Save state for next call
            self.prevTime  = self.currTime
            self.prevError = error

            return (self.kP * self.cP) + (self.kI * self.cI) + (self.kD * self.cD) # delta angle to apply to current servo angle
        else:
            deltaUpdate = (self.k1 * error) + (self.k2 * self.prevError[0]) + (self.k3 * self.prevError[1])

            self.prevError.appendleft(error)
            
            update = self.prevUpdate + deltaUpdate

            if update > self.maxOutput:
                update = self.maxOutput
            elif update < self.minOutput:
                update = self.minOutput
                
            self.prevUpdate = update
            
            return update