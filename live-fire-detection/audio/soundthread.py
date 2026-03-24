import threading
import time
from pathlib import Path
import simpleaudio as sa


class ThreadedSoundPlayer:
    def __init__(self, poll_interval: float = 0.02):
        """
        poll_interval: how often the worker checks for new commands while playing
        """
        self._poll_interval = poll_interval

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        self._shutdown = False
        self._stop_requested = False
        self._pending_path: str | None = None

        self._current_wave: sa.WaveObject | None = None
        self._current_play: sa.PlayObject | None = None
        self._current_path: str | None = None

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

        print("Initialized Audio Player")

    def play(self, file_path: str) -> None:
        """
        Request playback of a sound file.
        The most recent request takes priority and interrupts any current sound.
        """
        print("playing sound", file_path)
        path = str(Path(file_path).expanduser().resolve())

        with self._cv:
            self._pending_path = path
            self._stop_requested = False
            self._cv.notify()

    def stop(self) -> None:
        """
        Stop the currently playing sound and clear any pending play request.
        """
        with self._cv:
            self._pending_path = None
            self._stop_requested = True
            self._cv.notify()

        print("Stopping audio")

    def is_playing(self) -> bool:
        with self._lock:
            return self._current_play is not None and self._current_play.is_playing()

    def current_sound(self) -> str | None:
        with self._lock:
            return self._current_path

    def close(self) -> None:
        """
        Stop playback and shut down the worker thread.
        """
        with self._cv:
            self._shutdown = True
            self._pending_path = None
            self._stop_requested = True
            self._cv.notify()

        self._thread.join()

        print("Closing audio player")

    def _stop_current_locked(self) -> None:
        """
        Stop current playback. Caller must hold self._lock / self._cv lock.
        """
        if self._current_play is not None:
            try:
                self._current_play.stop()
            except Exception:
                pass

        self._current_play = None
        self._current_wave = None
        self._current_path = None

    def _worker(self) -> None:
        while True:
            with self._cv:
                while (
                    not self._shutdown
                    and self._pending_path is None
                    and not self._stop_requested
                ):
                    self._cv.wait()

                if self._shutdown:
                    self._stop_current_locked()
                    return

                if self._stop_requested:
                    self._stop_current_locked()
                    self._stop_requested = False
                    continue

                next_path = self._pending_path
                self._pending_path = None

                self._stop_current_locked()

            # Load and start playback outside the lock
            try:
                wave = sa.WaveObject.from_wave_file(next_path)
                play_obj = wave.play()
            except Exception as e:
                print(f"Failed to play '{next_path}': {e}")
                continue

            with self._cv:
                self._current_wave = wave
                self._current_play = play_obj
                self._current_path = next_path

            # Stay here until:
            # - sound finishes
            # - stop() is called
            # - a newer play() request arrives
            while True:
                with self._cv:
                    if self._shutdown:
                        self._stop_current_locked()
                        return

                    if self._stop_requested:
                        self._stop_current_locked()
                        self._stop_requested = False
                        break

                    if self._pending_path is not None:
                        # A newer sound request arrived; interrupt current one
                        self._stop_current_locked()
                        break

                    current = self._current_play

                if current is None or not current.is_playing():
                    with self._cv:
                        self._current_play = None
                        self._current_wave = None
                        self._current_path = None
                    break

                time.sleep(self._poll_interval)


if __name__ == "__main__":
    import time

    player = ThreadedSoundPlayer()

    player.play("/home/firedistinguisher/Music/testing/french_sfx.wav")
    time.sleep(10)

    # Interrupt sound1 and play sound2
    player.play("/home/firedistinguisher/Music/testing/chinese_sound_effect.wav")
    time.sleep(10)

    player.stop()

    player.close()
