import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Callable, Iterator

import serial


@dataclass
class CO2Sample:
    t_unix: float
    ppm: int
    raw_hex: str
    repeated: bool


class SEN0219UARTPoller:
    """
    SEN0219 UART poller (MH-Z style command 0x86).
    - Flush input
    - Send 9-byte command FF 01 86 00 00 00 00 00 79
    - Read 9-byte response
    - Validate header + checksum
    - Extract ppm = resp[2]*256 + resp[3]
    """

    CMD_READ_CO2 = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])

    def __init__(
        self,
        port: str,
        baud: int = 9600,
        *,
        poll_hz: float = 1.0,
        timeout_s: float = 0.25,
        inter_cmd_delay_s: float = 0.02,   # small settle time after write
        max_queue: int = 2000,
        reconnect: bool = True,
        reconnect_backoff_s: float = 1.0,
        ppm_min: int = 200,
        ppm_max: int = 100000,
    ):
        self.port = port
        self.baud = baud
        self.poll_hz = poll_hz
        self.timeout_s = timeout_s
        self.inter_cmd_delay_s = inter_cmd_delay_s
        self.reconnect = reconnect
        self.reconnect_backoff_s = reconnect_backoff_s
        self.ppm_min = ppm_min
        self.ppm_max = ppm_max

        self._ser: Optional[serial.Serial] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._q: "queue.Queue[CO2Sample]" = queue.Queue(maxsize=max_queue)
        self._latest: Optional[CO2Sample] = None
        self._latest_lock = threading.Lock()
        self._callbacks: list[Callable[[CO2Sample], None]] = []

        self._last_ppm: Optional[int] = None

    # ---------- public API ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._close()

    def latest(self) -> Optional[CO2Sample]:
        with self._latest_lock:
            return self._latest

    def get(self, timeout: Optional[float] = None) -> Optional[CO2Sample]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def samples(self) -> Iterator[CO2Sample]:
        while not self._stop.is_set():
            s = self.get(timeout=0.5)
            if s is not None:
                yield s

    def subscribe(self, cb: Callable[[CO2Sample], None]) -> None:
        self._callbacks.append(cb)

    # ---------- internals ----------
    @staticmethod
    def _checksum_ok(frame9: bytes) -> bool:
        """
        Many MH-Z style frames use checksum:
          checksum = 0xFF - (sum(bytes[1:8]) % 256) + 1
          frame[8] should equal checksum & 0xFF
        """
        if len(frame9) != 9:
            return False
        s = sum(frame9[1:8]) & 0xFF
        chk = (0xFF - s + 1) & 0xFF
        return frame9[8] == chk

    def _open(self) -> None:
        self._ser = serial.Serial(
            self.port,
            self.baud,
            timeout=self.timeout_s,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def _close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def _read_exact(self, n: int) -> bytes:
        """
        Read exactly n bytes or fewer if timeout. Uses Serial.timeout.
        """
        buf = bytearray()
        t0 = time.time()
        # give it up to ~2x timeout to accumulate bytes
        budget = max(0.05, self.timeout_s * 2.0)
        while len(buf) < n and (time.time() - t0) < budget:
            chunk = self._ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
        return bytes(buf)

    def _emit(self, sample: CO2Sample) -> None:
        with self._latest_lock:
            self._latest = sample

        try:
            self._q.put_nowait(sample)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(sample)
            except Exception:
                pass

        for cb in self._callbacks:
            try:
                cb(sample)
            except Exception:
                pass

    def _poll_once(self) -> Optional[CO2Sample]:
        # flush old bytes (Arduino equivalent)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            # fallback drain
            while self._ser.in_waiting:
                _ = self._ser.read(self._ser.in_waiting)

        # send command
        self._ser.write(self.CMD_READ_CO2)
        self._ser.flush()

        if self.inter_cmd_delay_s > 0:
            time.sleep(self.inter_cmd_delay_s)

        resp = self._read_exact(9)
        if len(resp) != 9:
            return None

        # header check
        if not (resp[0] == 0xFF and resp[1] == 0x86):
            return None

        # checksum check (recommended)
        if not self._checksum_ok(resp):
            return None

        ppm = (resp[2] << 8) | resp[3]
        if not (self.ppm_min <= ppm <= self.ppm_max):
            return None

        repeated = (self._last_ppm == ppm)
        self._last_ppm = ppm

        return CO2Sample(time.time(), ppm, resp.hex(), repeated)

    def _run(self) -> None:
        period = 1.0 / max(self.poll_hz, 0.01)
        next_t = time.time()

        while not self._stop.is_set():
            try:
                if self._ser is None or not self._ser.is_open:
                    self._open()

                now = time.time()
                if now < next_t:
                    time.sleep(min(0.01, next_t - now))
                    continue
                next_t += period

                sample = self._poll_once()
                if sample is not None:
                    self._emit(sample)

            except (serial.SerialException, OSError):
                self._close()
                if not self.reconnect:
                    break
                time.sleep(self.reconnect_backoff_s)
            except Exception:
                time.sleep(0.05)

        self._close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SEN0219 UART poll demo (FF 01 86 ...)")
    parser.add_argument("--port", required=True, help="e.g. /dev/ttyUSB0 or /dev/ttyTHS1")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--hz", type=float, default=5.0, help="poll rate (default 5 Hz like your Arduino)")
    parser.add_argument("--timeout", type=float, default=0.25)
    args = parser.parse_args()

    r = SEN0219UARTPoller(args.port, baud=args.baud, poll_hz=args.hz, timeout_s=args.timeout)
    r.start()
    print(f"[INFO] Polling {args.port} @ {args.baud} baud, {args.hz} Hz. Ctrl+C to stop.")

    try:
        for s in r.samples():
            rep = " (repeat)" if s.repeated else ""
            print(f"{s.t_unix:.3f}  CO2={s.ppm} ppm{rep}   raw={s.raw_hex}")
    except KeyboardInterrupt:
        pass
    finally:
        r.stop()

