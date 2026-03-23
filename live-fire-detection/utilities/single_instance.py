# utilities/single_instance.py
from __future__ import annotations
import os
import errno
import atexit

class SingleInstance:
    """
    Single-instance lock using an atomic lockfile.
    - lock_path should be on a local filesystem (e.g. /tmp).
    """
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self.fd = None

    def acquire(self) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self.fd = os.open(self.lock_path, flags, 0o644)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

            # Lock exists: check if PID is still running
            try:
                with open(self.lock_path, "r") as f:
                    pid_str = f.read().strip()
                pid = int(pid_str)
            except Exception:
                raise RuntimeError(f"Another instance may be running (lock exists): {self.lock_path}")

            if pid > 0 and _pid_is_running(pid):
                raise RuntimeError(f"Another instance is already running (pid {pid}).")
            else:
                # stale lock
                try:
                    os.remove(self.lock_path)
                except FileNotFoundError:
                    pass
                # retry acquire once
                self.fd = os.open(self.lock_path, flags, 0o644)

        # Write our PID into the file
        os.write(self.fd, str(os.getpid()).encode("ascii"))
        os.fsync(self.fd)

        atexit.register(self.release)

    def release(self) -> None:
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except Exception:
            pass

def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but not ours—treat as running
        return True

