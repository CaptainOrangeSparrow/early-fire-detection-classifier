# Authored by Michael Chung
# Date: 1/21/26
# ECE 464H

from smbus2 import SMBus
import time
import os

DEFAULT_I2C_BUS = 7 # For some reason, the jeteson I2C1 is on linux bus i2c-7

class ADC:
    def __init__(self, i2c_bus=None, bus_id=DEFAULT_I2C_BUS):
        self.bus_id = bus_id
        if i2c_bus == None:
            self.i2c_bus = SMBus(bus_id)
            self._owns_bus = True
        else:
            self.i2c_bus = i2c_bus
            self._owns_bus = False
        
        adc0 = ADS1115(0x48, self.i2c_bus)
        adc1 = ADS1115(0x49, self.i2c_bus, pga=1) # pga 1 = normal
        self.ads1115_list = [adc0, adc1]
    
    def get_i2c_bus(self):
        return self.i2c_bus

    def read(self, adc_device_index, adc_channel):
        # input validation
        if adc_device_index not in [0, 1] or adc_channel not in [0, 1, 2, 3]:
            return -1
        return self.ads1115_list[adc_device_index].read(adc_channel)

    def read4_once(self, adc_device_index):
        return self.ads1115_list[adc_device_index].read4_once()

    def get_meta_info(self):
        """
        Return a JSON-serializable dict describing the ADC subsystem.
        """
        return {
            "type": "ADC",
            "i2c": {
                "linux_bus_id": self.bus_id,
                "device_nodes": self._get_i2c_dev_nodes(self.bus_id),
                "owns_bus_handle": self._owns_bus,
            },
            "devices": [dev.get_meta_info() for dev in self.ads1115_list],
            "notes": [
                "Jetson I2C1 commonly appears as Linux i2c-7 depending on device tree / pins used."
            ],
        }

    def set_adc_channel_names(self, adc_idx, names_list):
        self.ads1115_list[adc_idx].set_channel_names(names_list)

    @staticmethod
    def _get_i2c_dev_nodes(bus_id: int):
        # Helpful for JSON/debug; safe if paths don’t exist.
        candidates = [
            f"/dev/i2c-{bus_id}",
            f"/sys/bus/i2c/devices/i2c-{bus_id}",
        ]
        return [p for p in candidates if os.path.exists(p)]


class ADS1115:

    PGA_FS_V = 4.096 # Voltage Scaling (Set by the 0xE3 command)
    DATA_RATE_SPS = 860 # Data rate also set by 0xE3 command

    def __init__(self, device_address=0x48, i2c_bus=None, bus_id=DEFAULT_I2C_BUS, pga=1):
        self.bus_id = bus_id
        if i2c_bus == None:
            self.i2c_bus = SMBus(bus_id)
            self._owns_bus = True
        else:
            self.i2c_bus = i2c_bus
            self._owns_bus = False

        self.device_address = device_address
        self.channel_names = [hex(device_address)+"_A0", hex(device_address)+"_A1", hex(device_address)+"_A2", hex(device_address)+"_A3"]
        
        self.pga = pga

    def get_i2c_bus(self):
        return self.i2c_bus

    def read(self, adc_channel):
        
        # Control reg mapping:
        # [15] = trigger read
        # [14:12] = adc channel (see datasheet)
        # [11:9] = PGA Gain
        # [7:5] = data rate (set this to 111 for 860 sps (fast))
        # Im too lazy to copy these - just see datasheet for ADS1115
        # But basically we need b11xx001111100011 for the write to the control reg where xx is the adc channel

        # PGA Gain:
        # 0 = 6.144V
        # 1 = 4.096V
        # 2 = 2.048V
        # 3 = 1.024V
        # 4 = 0.512V
        # 5 = 0.256V

        # Config register: single-shot, AIN0-3 vs GND, gain=1, 128SPS
        cmd = 0x81 | ((self.pga & 0x7) << 1) | (int(adc_channel + 4) << 4) # shift 12, but since high byte, shift by 4

        #reg 0x00 is data reg, reg 0x01 is control reg
        self.i2c_bus.write_i2c_block_data(self.device_address, 0x01, [cmd, 0xE3])
        data = self.i2c_bus.read_i2c_block_data(self.device_address, 0x00, 2)
        
        # big endian return
        raw = (data[0] << 8) | data[1]
        if raw > 0x7FFF:
            raw -= 0x10000 # value is signed two's complement

        #voltage = raw * 4.096 / 32767.0 # convert to voltage if desired
        #^assuming pga=1 (4.096)

        # Note, max raw value is 32767 taking into account two's complement
        # However, we are using PGA scale set to 4.096V, which means Ain of 4.096V = 32767.
        # Since our VCC will be 3.3V, the max ADC value we expect is 26400 or 26399.
        return raw
    
    def _wait_ready(self, timeout_s=0.01):
        t0 = time.perf_counter()
        while True:
            cfg = self.i2c_bus.read_i2c_block_data(self.device_address, 0x01, 2)
            if cfg[0] & 0x80:  # OS bit (bit 15)
                return True
            if (time.perf_counter() - t0) > timeout_s:
                return False
            time.sleep(0.0002)

    def _read_conv(self):
        data = self.i2c_bus.read_i2c_block_data(self.device_address, 0x00, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 0x7FFF:
            raw -= 0x10000
        return raw

    def read4_once(self, discard_first=True):
        vals = []
        for ch in (0, 1, 2, 3):
            high = 0x81 | ((self.pga & 0x7) << 1) | ((ch + 4) << 4)

            # start conversion
            self.i2c_bus.write_i2c_block_data(self.device_address, 0x01, [high, 0xE3])
            self._wait_ready()
            _ = self._read_conv()       # first read

            if discard_first:
                self.i2c_bus.write_i2c_block_data(self.device_address, 0x01, [high, 0xE3])
                self._wait_ready()

            vals.append(self._read_conv())
        return vals

    def set_channel_names(self, names_list):
        self.channel_names = [o if n is None else n for o, n in zip(self.channel_names, names_list)]

    def get_meta_info(self, include_live_registers: bool = False):
        """
        Return a JSON-serializable dict describing this ADS1115 instance.
        If include_live_registers=True, attempts to read config/conversion regs (can raise if device missing).
        """
        meta = {
            "type": "ADS1115",
            "address_hex": hex(self.device_address),
            "address_int": int(self.device_address),
            "i2c": {
                "linux_bus_id": self.bus_id,
                "device_node": f"/dev/i2c-{self.bus_id}",
                "owns_bus_handle": self._owns_bus,
            },
            "configuration_intent": {
                "mode": "single-shot",
                "inputs": "AINx vs GND (single-ended)",
                "pga_full_scale_v": self.PGA_FS_V,
                "data_rate_sps": self.DATA_RATE_SPS,
                "comparator": "disabled",
                "note": "These reflect what read()/read4_once() program into config reg (0x01).",
            },
            "channels": [
                {"channel": 0, "mux_bits": "100", "signal": "AIN0-GND", "name": self.channel_names[0]},
                {"channel": 1, "mux_bits": "101", "signal": "AIN1-GND", "name": self.channel_names[1]},
                {"channel": 2, "mux_bits": "110", "signal": "AIN2-GND", "name": self.channel_names[2]},
                {"channel": 3, "mux_bits": "111", "signal": "AIN3-GND", "name": self.channel_names[3]},
            ],
            "raw_output": {
                "type": "int16",
                "two_complement": True,
                "expected_max_raw_at_vcc_3v3": 26400,
            },
        }

        if include_live_registers:
            cfg = self.i2c_bus.read_i2c_block_data(self.device_address, 0x01, 2)
            conv = self.i2c_bus.read_i2c_block_data(self.device_address, 0x00, 2)
            meta["live_registers"] = {
                "config_reg_0x01": {
                    "bytes": [int(cfg[0]), int(cfg[1])],
                    "hex": f"0x{cfg[0]:02X}{cfg[1]:02X}",
                },
                "conv_reg_0x00": {
                    "bytes": [int(conv[0]), int(conv[1])],
                    "hex": f"0x{conv[0]:02X}{conv[1]:02X}",
                },
            }

        return meta

# Demo:
if __name__ == "__main__":
    adc = ADC()
    while True:
        value = adc.read(0, 2)
        time.sleep(0.5)
        print('Reading Channel A2 value on ADC0 (0-26400 for 3.3V) =', value)

