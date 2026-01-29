## Authored by Michael Chung


from smbus2 import SMBus
import time

DEFAULT_I2C_BUS = 7 # For some reason, the jeteson I2C1 is on linux bus i2c-7

class ADC:
    def __init__(self, i2c_bus=None, bus_id=DEFAULT_I2C_BUS):
        if i2c_bus == None:
            self.i2c_bus = SMBus(bus_id)
        else:
            self.i2c_bus = i2c_bus

        self.adc_address_array = [0x48, 0x49] # since we have two of them

    def read(self, adc_device_index, adc_channel):
        # input validation
        if adc_device_index not in [0, 1] or adc_channel not in [0, 1, 2, 3]:
            return -1

        device_address = self.adc_address_array[adc_device_index]
        
        # Control reg mapping:
        # [15] = trigger read
        # [14:12] = adc channel (see datasheet)
        # Im too lazy to copy these - just see datasheet for ADS1115
        # But basically we need b11xx001111100011 for the write to the control reg where xx is the adc channel

        # Config register: single-shot, AIN0-3 vs GND, gain=1, 128SPS
        cmd = 0x83 | (int(adc_channel + 4) << 4) # shift 12, but since high byte, shift by 4

        #reg 0x00 is data reg, reg 0x01 is control reg
        self.i2c_bus.write_i2c_block_data(device_address, 0x01, [cmd, 0xE3])
        data = self.i2c_bus.read_i2c_block_data(device_address, 0x00, 2)
        
        # big endian return
        raw = (data[0] << 8) | data[1]
        if raw > 0x7FFF:
            raw -= 0x10000 # value is signed two's complement

        #voltage = raw * 4.096 / 32767.0 # convert to voltage if desired
        
        # Note, max raw value is 32767 taking into account two's complement
        # However, we are using PGA scale set to 4.096V, which means Ain of 4.096V = 32767.
        # Since our VCC will be 3.3V, the max ADC value we expect is 26400 or 26399.
        return raw

# Demo:
if __name__ == "__main__":
    adc = ADC()
    while True:
        value = adc.read(0, 2)
        time.sleep(0.5)
        print('Reading Channel A2 value on ADC0 (0-26400 for 3.3V) =', value)

