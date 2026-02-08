import re
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
    raw: str


class SEN0219Serial:
    """
    Robust streaming UART reader for SEN0219-style CO2 text output.
    """

    _ppm_regexes = [
        re.compile(r"(?:co2|ppm)\s*[:=]?\s*(\d{2,6})", re.IGNORECASE),
        re.compile(r"(\d{2,6})\s*ppm", re.IGNORECASE),
        re.compile(r"^\s*(\d{2,6})\s*$"),
    ]

    def __init__(
        self,
        port: str,
        baud: int = 9600,
        *,
        timeout_s: float = 1.0,
        max_queue: int = 2000,
        reconnect: bool = True,
        reconnect_backoff_s: float = 1.0,
        ppm_min: int = 200,
        ppm_max: int = 100000,
    ):
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
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
        self._close_serial()

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

    def _open_serial(self) -> None:
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

    def _close_serial(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def _parse_ppm(self, line: str) -> Optional[int]:
        for rgx in self._ppm_regexes:
            m = rgx.search(line)
            if m:
                try:
                    ppm = int(m.group(1))
                except Exception:
                    continue
                if self.ppm_min <= ppm <= self.ppm_max:
                    return ppm
        return None

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

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._ser is None or not self._ser.is_open:
                    self._open_serial()

                raw = self._ser.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                ppm = self._parse_ppm(line)
                if ppm is None:
                    continue

                self._emit(CO2Sample(time.time(), ppm, line))

            except (serial.SerialException, OSError):
                self._close_serial()
                if not self.reconnect:
                    break
                time.sleep(self.reconnect_backoff_s)
            except Exception:
                time.sleep(0.05)

        self._close_serial()


# ==========================================================
# Demo / CLI usage
# ==========================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SEN0219 CO2 UART reader demo")
    parser.add_argument("--port", required=True, help="Serial port (e.g. /dev/ttyUSB0 or /dev/ttyTHS1)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--print-every", type=float, default=1.0,
                        help="Seconds between 'latest' printouts")
    args = parser.parse_args()

    reader = SEN0219Serial(args.port, args.baud)
    reader.start()

    print(f"[INFO] Reading SEN0219 on {args.port} @ {args.baud} baud")
    print("[INFO] Ctrl+C to exit\n")

    last_print = 0.0

    try:
        for sample in reader.samples():
            # continuous stream (comment this out if too verbose)
            print(f"{sample.t_unix:.3f}  CO2={sample.ppm} ppm")

            # periodic probe demo
            now = time.time()
            if now - last_print >= args.print_every:
                latest = reader.latest()
                if latest:
                    print(f"[LATEST] {latest.ppm} ppm")
                last_print = now

    except KeyboardInterrupt:
        print("\n[INFO] Stopping...")
    finally:
        reader.stop()

