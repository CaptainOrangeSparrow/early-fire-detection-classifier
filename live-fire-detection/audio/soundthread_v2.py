import threading
import time
from pathlib import Path
import simpleaudio as sa
import wave
import numpy as np

class ThreadedSoundPlayer:
    
    main_player = None

    def __init__(self, poll_interval: float = 0.02, volume: float = 1.0):
        self._poll_interval = poll_interval
        self._volume = self._clamp_volume(volume)
        self._pending_volume = None
        self._pending_path = None

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
    
    @staticmethod
    def set_main_player(player):
        ThreadedSoundPlayer.main_player = player

    def _normalize_path(self, file_path: str) -> str:
        return str(Path(file_path).expanduser().resolve())

    def _clamp_volume(self, volume: float) -> float:
        return max(0.0, min(float(volume), 1.0))

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._volume = self._clamp_volume(volume)

    def get_volume(self) -> float:
        with self._lock:
            return self._volume

    def _build_wave_object_with_volume(self, file_path: str, volume: float) -> sa.WaveObject:
        with wave.open(file_path, "rb") as wf:
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            audio_bytes = wf.readframes(wf.getnframes())

        if sample_width == 1:
            # 8-bit PCM WAV is unsigned
            audio = np.frombuffer(audio_bytes, dtype=np.uint8).astype(np.float32)
            audio = (audio - 128.0) * volume + 128.0
            audio = np.clip(audio, 0, 255).astype(np.uint8)

        elif sample_width == 2:
            # 16-bit PCM WAV is signed
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            audio *= volume
            audio = np.clip(audio, -32768, 32767).astype(np.int16)

        else:
            raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")

        return sa.WaveObject(
            audio.tobytes(),
            num_channels=num_channels,
            bytes_per_sample=sample_width,
            sample_rate=sample_rate,
        )

    def play(self, file_path: str, volume: float | None = None) -> None:
        """
        Request playback of a sound file.

        Behavior:
        - If the same sound is already playing, do nothing.
        - If the same sound is already pending, do nothing.
        - If a different sound is playing or pending, the most recent one wins.
        """
        path = self._normalize_path(file_path)

        with self._cv:
            requested_volume = None if volume is None else self._clamp_volume(volume)

            current_is_playing = (
                self._current_path == path
                and self._current_play is not None
                and self._current_play.is_playing()
                and requested_volume is None
            )
            pending_is_same = (
                self._pending_path == path
                and self._pending_volume == requested_volume
            )

            if current_is_playing or pending_is_same:
                return

            self._pending_path = path
            self._pending_volume = requested_volume
            self._stop_requested = False
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._pending_path = None
            self._pending_volume = None
            self._stop_requested = True
            self._cv.notify()

    def is_playing(self) -> bool:
        with self._lock:
            return self._current_play is not None and self._current_play.is_playing()

    def current_sound(self) -> str | None:
        with self._lock:
            return self._current_path

    def close(self) -> None:
        with self._cv:
            self._shutdown = True
            self._pending_path = None
            self._pending_volume = None
            self._stop_requested = True
            self._cv.notify()

        self._thread.join()

    def _stop_current_locked(self) -> None:
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
                next_volume = self._pending_volume
                self._pending_path = None
                self._pending_volume = None

                # If the exact same sound is still playing, ignore request.
                if (
                    next_path == self._current_path
                    and self._current_play is not None
                    and self._current_play.is_playing()
                ):
                    continue

                # Different sound requested: interrupt current playback.
                self._stop_current_locked()

            try:
                if next_volume is None:
                    with self._lock:
                        volume = self._volume
                else:
                    volume = next_volume

                #wave = sa.WaveObject.from_wave_file(next_path)
                wave = self._build_wave_object_with_volume(next_path, volume)
                play_obj = wave.play()

            except Exception as e:
                print(f"Failed to play '{next_path}': {e}")
                continue

            with self._cv:
                self._current_wave = wave
                self._current_play = play_obj
                self._current_path = next_path

            while True:
                with self._cv:
                    if self._shutdown:
                        self._stop_current_locked()
                        return

                    if self._stop_requested:
                        self._stop_current_locked()
                        self._stop_requested = False
                        break

                    # If a new request comes in:
                    if self._pending_path is not None:
                        # Same sound as current: ignore it and keep playing.
                        if self._pending_path == self._current_path:
                            self._pending_path = None
                        else:
                            # Different sound: interrupt current and handle new one.
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

    player.play("/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/audio/library/french_sfx.wav", volume=0.1)
    time.sleep(3)

    # Interrupt sound1 and play sound2
    player.play("/home/firedistinguisher/projects/early-fire-detection-classifier/live-fire-detection/audio/library/french_sfx.wav", volume=0.1)
    time.sleep(10)

    player.stop()

    player.close()

