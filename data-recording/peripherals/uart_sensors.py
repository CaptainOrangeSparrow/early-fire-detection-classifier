import time
from dataclasses import dataclass
from typing import Optional

import serial


class UARTDevice:
    """
    Minimal UART device base:
    - owns the Serial object
    - provides open/close + read/write helpers
    - NO threads, NO queues
    """

    def __init__(
        self,
        *,
        port: str,
        baud: int,
        timeout_s: float = 0.25,
        inter_cmd_delay_s: float = 0.0,
    ):
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self.inter_cmd_delay_s = inter_cmd_delay_s
        self._ser: Optional[serial.Serial] = None

    # --- lifecycle ---
    def open(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return
        self._ser = serial.Serial(
            self.port,
            self.baud,
            timeout=self.timeout_s,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        self.flush_input()

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # --- helpers ---
    def flush_input(self) -> None:
        if not self.is_open:
            return
        try:
            self._ser.reset_input_buffer()
        except Exception:
            # fallback drain
            while getattr(self._ser, "in_waiting", 0):
                _ = self._ser.read(self._ser.in_waiting)

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise RuntimeError("UART not open")
        self._ser.write(data)
        self._ser.flush()
        if self.inter_cmd_delay_s > 0:
            time.sleep(self.inter_cmd_delay_s)

    def read_exact(self, n: int, *, budget_s: Optional[float] = None) -> bytes:
        """
        Read exactly n bytes or fewer if overall budget expires.
        Serial timeout still applies per read call.
        """
        if not self.is_open:
            raise RuntimeError("UART not open")

        buf = bytearray()
        t0 = time.time()
        budget = budget_s if budget_s is not None else max(0.05, self.timeout_s * 2.0)

        while len(buf) < n and (time.time() - t0) < budget:
            chunk = self._ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
        return bytes(buf)

#########################################################3

# SEN0219 NDIR CO2 Sensor

@dataclass
class CO2Sample:
    t: float # t_unix
    ppm: int
    raw_hex: str
    repeated: bool


class SEN0219(UARTDevice):
    DEFAULT_PORT = "/dev/ttyUSB0"   # set once
    DEFAULT_BAUD = 9600

    CMD_READ_CO2 = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])

    def __init__(
        self,
        *,
        port: str = DEFAULT_PORT,
        timeout_s: float = 0.25,
        ppm_min: int = 200,
        ppm_max: int = 100000,
    ):
        super().__init__(
            port=port,
            baud=self.DEFAULT_BAUD,
            timeout_s=timeout_s,
            inter_cmd_delay_s=0.02,
        )
        self.ppm_min = ppm_min
        self.ppm_max = ppm_max
        self._last_ppm: Optional[int] = None

    @staticmethod
    def checksum_ok(frame9: bytes) -> bool:
        if len(frame9) != 9:
            return False
        s = sum(frame9[1:8]) & 0xFF
        chk = (0xFF - s + 1) & 0xFF
        return frame9[8] == chk

    def read_sample(self) -> Optional[CO2Sample]:
        """
        One request/response transaction. No timing, no threading.
        Returns CO2Sample or None if invalid/timeout.
        """
        if not self.is_open:
            self.open()

        self.flush_input()
        self.write(self.CMD_READ_CO2)

        resp = self.read_exact(9)
        if len(resp) != 9:
            return None
        if not (resp[0] == 0xFF and resp[1] == 0x86):
            return None
        if not self.checksum_ok(resp):
            return None

        ppm = (resp[2] << 8) | resp[3]
        if not (self.ppm_min <= ppm <= self.ppm_max):
            return None

        repeated = (self._last_ppm == ppm)
        self._last_ppm = ppm
        return CO2Sample(time.perf_counter(), ppm, resp.hex(), repeated)

    def get_meta_info(self) -> dict:
        """
        JSON-safe metadata for logging/telemetry.
        """
        return {
            "sensor": "SEN0219",
            "gas": "CO2",
            "iface": "uart",
            "port": self.port,
            "baud": self.baud,
            "timeout_s": float(self.timeout_s),
            "inter_cmd_delay_s": float(self.inter_cmd_delay_s),
            "protocol": "MH-Z/0x86-like",
            "units": "ppm",
            "ppm_min": int(self.ppm_min),
            "ppm_max": int(self.ppm_max),
        }

##############################################################

# ZE07-CO Electrochemical CO Sensor

# CO packet is same as CO2 packet
# @dataclass
# class COSample:
#     t_unix: float
#     ppm: float
#     raw_hex: str
#     repeated: bool


class ZE07CO(UARTDevice):
    DEFAULT_PORT = "/dev/ttyTHS1"
    DEFAULT_BAUD = 9600

    CMD_SWITCH_TO_QA = bytes([0xFF, 0x01, 0x78, 0x41, 0x00, 0x00, 0x00, 0x00, 0x46])
    CMD_READ         = bytes([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])

    def __init__(
        self,
        *,
        port: str = DEFAULT_PORT,
        timeout_s: float = 0.25,
        ppm_min: float = 0.0,
        ppm_max: float = 5000.0,
        switch_to_qa_on_open: bool = True,
    ):
        super().__init__(
            port=port,
            baud=self.DEFAULT_BAUD,
            timeout_s=timeout_s,
            inter_cmd_delay_s=0.02,
        )
        self.ppm_min = ppm_min
        self.ppm_max = ppm_max
        self.switch_to_qa_on_open = switch_to_qa_on_open

        self._last_ppm: Optional[float] = None
        self._qa_configured = False

    @staticmethod
    def checksum_ok(frame9: bytes) -> bool:
        # Winsen checksum: (~(sum(frame[1:8])&0xFF)+1)&0xFF
        if len(frame9) != 9:
            return False
        s = sum(frame9[1:8]) & 0xFF
        chk = ((~s) + 1) & 0xFF
        return frame9[8] == chk

    def open(self) -> None:
        super().open()
        if self.switch_to_qa_on_open and not self._qa_configured:
            self.write(self.CMD_SWITCH_TO_QA)
            time.sleep(0.15)
            self.flush_input()
            self._qa_configured = True

    def _read_frame9_resync(self, *, budget_s: float = 1.0) -> Optional[bytes]:
        """
        Scan until we see 0xFF, then read 8 more bytes.
        """
        if not self.is_open:
            self.open()

        t0 = time.time()
        while (time.time() - t0) < budget_s:
            b = self.read_exact(1, budget_s=budget_s)
            if len(b) != 1:
                continue
            if b[0] != 0xFF:
                continue
            rest = self.read_exact(8, budget_s=max(0.05, budget_s - (time.time() - t0)))
            if len(rest) != 8:
                continue
            return b + rest
        return None

    def read_sample(self) -> Optional[CO2Sample]:
        """
        One request/response transaction in QA mode.
        Returns COSample or None if invalid/timeout.
        """
        if not self.is_open:
            self.open()

        # Key step for QA mode: clear any old bytes so we read THIS reply
        self.flush_input()

        self.write(self.CMD_READ)

        frame = self._read_frame9_resync(budget_s=1.0)
        if frame is None or len(frame) != 9:
            return None

        # QA reply should be [FF, 86, conc_hi, conc_lo, 00, 00, range_hi, range_lo, cs]
        if frame[1] != 0x86:
            return None
        if not self.checksum_ok(frame):
            return None

        conc_raw = (frame[2] << 8) | frame[3]
        ppm = conc_raw * 0.1

        if not (self.ppm_min <= ppm <= self.ppm_max):
            print("CO Sample out of range!! ppm=", ppm)
            #return None

        repeated = (self._last_ppm == ppm)
        self._last_ppm = ppm

        return CO2Sample(time.perf_counter(), ppm, frame.hex(), repeated)

    def get_meta_info(self) -> dict:
        """
        JSON-safe metadata for logging/telemetry.
        """
        return {
            "sensor": "ZE07-CO",
            "gas": "CO",
            "iface": "uart",
            "port": self.port,
            "baud": self.baud,
            "timeout_s": float(self.timeout_s),
            "inter_cmd_delay_s": float(self.inter_cmd_delay_s),
            "mode": "qa",  # if you keep a mode attribute, use self.mode instead
            "protocol": "Winsen 9-byte",
            "units": "ppm",
            "resolution_ppm": 0.1,
            "ppm_min": float(self.ppm_min),
            "ppm_max": float(self.ppm_max),
        }




