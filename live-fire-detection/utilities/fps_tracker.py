import time

class FPSTracker:
    def __init__(self, window_s: float = 1.0):
        self.window_s = window_s
        self._t0 = time.perf_counter()
        self._n = 0
        self._fps = 0.0

    def tick(self, n: int = 1):
        """Call whenever a frame/event occurs."""
        self._n += n
        now = time.perf_counter()
        dt = now - self._t0
        if dt >= self.window_s:
            self._fps = self._n / dt
            self._n = 0
            self._t0 = now

    def get_fps(self) -> float:
        """Return the most recent FPS estimate."""
        return self._fps

