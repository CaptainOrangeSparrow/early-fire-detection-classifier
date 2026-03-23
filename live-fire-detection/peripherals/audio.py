from __future__ import annotations

import os
import time
import queue
import threading
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union
from pathlib import Path

class AlertType(Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    RECORD_START = "record_start"
    RECORD_STOP = "record_stop"


@dataclass(frozen=True)
class AlertSpec:
    filename: str
    min_interval_s: float = 0.0  # cooldown per alert


# Queue item: either sentinel or (alert_type, command_list)
QueueItem = Union[object, Tuple[AlertType, list[str]]]

BASE_DIR = Path(__file__).resolve().parent
WAV_DIR = BASE_DIR / "sounds"

class AudioAlertPlayer:
    """
    Non-blocking alert player using a background worker that runs `aplay`.
    Optional dedupe prevents enqueuing the same alert type if it's already queued/playing.
    """

    _SENTINEL = object()

    def __init__(
        self,
        wav_dir: str | None = None,
        device: str = "plughw:1,0",
        queue_size: int = 8,
        mapping: Optional[Dict[AlertType, AlertSpec]] = None,
        stop_evt: Optional[threading.Event] = None,
        dedupe_enabled: bool = True,   # <-- in-code var/option
    ):
        if wave_dir is None:
            self.wave_dir = WAV_DIR
        else :
            self.wav_dir = Path(wav_dir).resolve()
        self.device = device
        self.q: "queue.Queue[QueueItem]" = queue.Queue(maxsize=queue_size)

        self.mapping: Dict[AlertType, AlertSpec] = mapping or {
            AlertType.INFO: AlertSpec("info.wav", 0.0),
            AlertType.WARN: AlertSpec("warn.wav", 1.0),
            AlertType.ERROR: AlertSpec("error.wav", 0.5),
            AlertType.RECORD_START: AlertSpec("record_start.wav", 0.0),
            AlertType.RECORD_STOP: AlertSpec("record_stop.wav", 0.0),
        }

        self.stop_evt = stop_evt or threading.Event()
        self.dedupe_enabled = dedupe_enabled

        self._last_play: Dict[AlertType, float] = {}
        self._thread: Optional[threading.Thread] = None

        # Tracks alert types that are queued or currently playing
        self._pending: set[AlertType] = set()
        self._lock = threading.Lock()

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.worker, args=(self.stop_evt,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_evt.set()
        try:
            self.q.put_nowait(self._SENTINEL)
        except queue.Full:
            pass

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    # ---------- worker ----------
    def worker(self, stop_evt: threading.Event) -> None:
        while not stop_evt.is_set():
            try:
                item = self.q.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if item is self._SENTINEL:
                    break

                alert_type, cmd = item  # type: ignore[misc]

                # Mark as "playing" (it is already pending; keep it pending until done)
                subprocess.run(cmd, check=False)

            finally:
                # Clear pending state for this alert type after playback finishes
                if item is not self._SENTINEL:
                    alert_type, _ = item  # type: ignore[misc]
                    with self._lock:
                        self._pending.discard(alert_type)
                self.q.task_done()

    # ---------- enqueue ----------
    def play_alert(self, alert_type: AlertType) -> bool:
        """
        Returns True if enqueued, False if dropped due to:
        - stop requested
        - cooldown active
        - dedupe prevented enqueue
        - queue full
        """
        if self.stop_evt.is_set():
            return False

        spec = self.mapping.get(alert_type)
        if spec is None:
            raise KeyError(f"No mapping for {alert_type}")

        # Cooldown check (based on last time we successfully enqueued)
        now = time.time()
        last = self._last_play.get(alert_type, 0.0)
        if spec.min_interval_s > 0 and (now - last) < spec.min_interval_s:
            return False

        # Dedupe check: skip if already queued or playing
        if self.dedupe_enabled:
            with self._lock:
                if alert_type in self._pending:
                    return False

        path = os.path.join(self.wav_dir, spec.filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Alert WAV not found: {path}")

        cmd = ["aplay", "-D", self.device, path]
        item: QueueItem = (alert_type, cmd)

        try:
            # Once we enqueue, mark as pending immediately
            with self._lock:
                if self.dedupe_enabled and alert_type in self._pending:
                    return False
                self._pending.add(alert_type)

            self.q.put_nowait(item)
            self._last_play[alert_type] = now
            return True

        except queue.Full:
            # If enqueue failed, roll back pending marker
            with self._lock:
                self._pending.discard(alert_type)
            return False

def main():
    audio = AudioAlertPlayer()
    audio.start()

    audio.play_alert(AlertType.RECORD_START)
    time.sleep(1)

    audio.play_alert(AlertType.WARN)
    time.sleep(0.2)

    # This one will be deduped if WARN is still pending
    audio.play_alert(AlertType.WARN)

    # Different alert plays even if WARN is pending
    audio.play_alert(AlertType.ERROR)

    time.sleep(5)


if __name__ == "__main__":
    main()


