import smbus2

# I2C has been enabled on the jetson

bus = smbus2.SMBus(0)
address = 0x60 # <-- Change this to match the ADC one

# write
bus.write_bye_data(address, 0x0, value) # device address, register address, value

# read
bus.read_byte_data(address, 0x1) # device address, register address

