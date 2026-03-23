import sys
import select
import termios
import tty

class TerminalKeyWatcher:
    def __init__(self):
        self._fd = None
        self._old = None

    def __enter__(self):
        if not sys.stdin.isatty():
            return self
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._old is not None and self._fd is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

def poll_quit_key(quit_chars=("q", "Q")) -> bool:
    """Non-blocking; safe to call inside a Qt timer callback."""
    try:
        if not sys.stdin.isatty():
            return False
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            return False

        # Read a single byte/char. In cbreak mode this should not block
        ch = sys.stdin.read(1)
        return ch in quit_chars

    except (KeyboardInterrupt, SystemExit):
        # Let main handle SIGINT; don't wedge Qt callback
        raise
    except Exception:
        # Never crash the GUI loop because stdin did something weird
        return False

