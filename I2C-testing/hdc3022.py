# Authored by Michael Chung
# Date: 1/22/26
# ECE 464H

from smbus2 import SMBus, i2c_msg
import time

DEFAULT_I2C_BUS = 7 # For some reason, the jetson I2C1 is on linux bus i2c-7

class HDC3022:
    def __init__(self, device_address=0x44, i2c_bus=None, bus_id=DEFAULT_I2C_BUS):
        if i2c_bus == None:
            self.i2c_bus = SMBus(bus_id)
        else:
            self.i2c_bus = i2c_bus

        self.address = device_address

    def get_i2c_bus(self):
        return self.i2c_bus

    def read_temp_rh(self) -> tuple[float, float]:

        # Trigger-on-demand command (MSB, LSB)
        CMD = bytes([0x24, 0x00])
        # TI recommends >=15 ms for highest resolution/repeatability in trigger-on-demand examples
        CONVERSION_DELAY_S = 0.015

        # Write the 2-byte command (no "register"; it's a command word)
        self.i2c_bus.i2c_rdwr(i2c_msg.write(self.address, CMD))

        time.sleep(CONVERSION_DELAY_S)

        # Read 6 bytes: T_MSB, T_LSB, T_CRC, RH_MSB, RH_LSB, RH_CRC
        rd = i2c_msg.read(self.address, 6)
        self.i2c_bus.i2c_rdwr(rd)
        data = list(rd)

        raw_t  = (data[0] << 8) | data[1]
        raw_rh = (data[3] << 8) | data[4]

        temp_c = (raw_t / 65535.0) * 175.0 - 45.0
        rh_pct = (raw_rh / 65535.0) * 100.0

        return temp_c, rh_pct

# demo
if __name__ == "__main__":
    print("HDC3022 Demo")
    period_s = 0.5
    hdc = HDC3022()
    while True:
        try:
            t, rh = hdc.read_temp_rh()
            print(f"T = {t:7.3f} °C | RH = {rh:7.3f} %")
        except OSError as e:
            # Typical if bus glitches / device NACKs occasionally
            print(f"I2C error: {e}")
        time.sleep(period_s)


