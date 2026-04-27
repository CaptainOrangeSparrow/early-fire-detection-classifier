import time
import spidev
import Jetson.GPIO as GPIO

import math

# Example pins — change to your actual wiring
# FS_PIN = 11   # BOARD numbering example
# CS_GPIO_PIN = 36  # only if you want manual CS instead of hardware CS

class TLV5616:

    SPI_SPEED = 1000000
    SPI_MODE = 0

    def __init__(self, spi_bus, spi_dev, fs_pin, cs_pin, spi_speed=SPI_SPEED):
        self.spi_bus = spi_bus
        self.spi_dev = spi_dev
        self.fs_pin = fs_pin
        self.cs_pin = cs_pin
        self.spi_speed = spi_speed

        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.fs_pin, GPIO.OUT, initial=GPIO.HIGH)
        
        # Manual CS
        GPIO.setup(self.cs_pin, GPIO.OUT, initial=GPIO.HIGH)

        self.spi = spidev.SpiDev()
        self.spi.open(self.spi_bus, self.spi_dev)
        self.spi.max_speed_hz = self.spi_speed
        self.spi.mode = TLV5616.SPI_MODE

    def dac_out(self, value):
        tx = TLV5616.tlv5616_word(int(value), 0b0000)

        # Manual CS and Frame Select
        GPIO.output(self.cs_pin, GPIO.LOW)
        GPIO.output(self.fs_pin, GPIO.LOW)

        time.sleep(1e-6) # adjust to datasheet timing
        self.spi.xfer2(tx)
        time.sleep(1e-6) # adjust to datasheet timing
            
        GPIO.output(self.fs_pin, GPIO.HIGH)
        GPIO.output(self.cs_pin, GPIO.HIGH)

    @staticmethod
    def tlv5616_word(data12, ctrl4):
        """Build 16-bit word: 4 control bits + 12 data bits."""
        word = ((ctrl4 & 0xF) << 12) | (data12 & 0xFFF)
        return [(word >> 8) & 0xFF, word & 0xFF]


    def close(self):
        self.spi.close()
        GPIO.cleanup([self.fs_pin, self.cs_pin])


def main():
    dac = TLV5616(spi_bus=1, spi_dev=0, fs_pin=11, cs_pin=36)
    sine = False
    ramp = True
    try:
        
        sample_rate_hz=1000
        sine_freq_hz=0.12

        phase=0.0
        dt = 1.0 / sample_rate_hz
        phase_step = 2.0 * math.pi * sine_freq_hz / sample_rate_hz
        next_t = time.perf_counter()

        while sine:
            y = 0.5 + 0.49 * math.sin(phase)

            if y < 0.0:
                y = 0.0
            elif y > 1.0:
                y = 1.0

            dac_code = int(round(y * 1023))
            dac.dac_out(dac_code)

            phase += phase_step
            if phase >= 2.0 * math.pi:
                phase -= 2.0 * math.pi

            next_t += dt
            sleep_time = next_t - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # If timing slips, resync to avoid runaway lag
                next_t = time.perf_counter()
        
        ramp_step = 0.2
        pos = 0
        direction = 1
        while ramp:
            dac.dac_out(int(pos))
            time.sleep(dt)
            pos += (ramp_step * direction)
            if pos < 0:
                direction = 1
                pos = 0
            if pos > 1023:
                direction = -1
                pos = 1023

        dac.dac_out(0xFFF)
        time.sleep(5)
        dac.dac_out(0x000)
        #time.sleep(1)
        #dac.dac_out(0x400)
        #time.sleep(1)
        #dac.dac_out(0x000)
    finally:
        dac.close()
        print("Dac closed.")

if __name__ == "__main__":
    main()
