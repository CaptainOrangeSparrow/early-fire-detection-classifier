import time


class PID:
    """
    Tuning order:
        1. Set kI = kD = 0. Raise kP until the mount oscillates.
           Then halve kP.
        2. Raise kI until drift is eliminated.
        3. Raise kD until overshoot is damped.
    """

    def __init__(self, kP: float = 1.0, kI: float = 0.0, kD: float = 0.0):
        self.kP = kP
        self.kI = kI
        self.kD = kD


    def initialize(self):
        # Reset states for new tracking target
        self.currTime  = time.time()
        self.prevTime  = self.currTime
        self.prevError = 0.0

        # Term accumulators
        self.cP = 0.0
        self.cI = 0.0
        self.cD = 0.0

    def update(self, error: float) -> float:
        """
        Compute the PID correction for the current normalised error.

        error: Tracking Error in degrees 

        Returns:
            Angle delta in degrees to add to the current servo angle.
        """
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