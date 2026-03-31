from peripherals.adc import ADC
from scipy.signal import welch, filtfilt, iirnotch, butter
import time
from collections import deque
import numpy as np
import matplotlib.pyplot as plt

def main():
    adc = ADC()
    fs = 1000 # Sampling Frequency 

    channels = [deque() for _ in range(8)]
    now = time.time()
    
    # Collect data for 60 seconds
    while time.time() - now < 60:
        
        values = adc.read4_once(0) + adc.read4_once(1)  
        print(f"Collecting data... {int(time.time() - now)}s", end='\r')
        
        for ch in range(len(values)):
            channels[ch].append(values[ch])
            
        time.sleep(1/fs) 
    
    # Analyze and plot the data for each channel
    for ch in range(8):
        data = list(channels[ch])
        
        max = np.max(data)
        min = np.min(data)
        
        print(f"Channel {ch+1} - Min: {min}, Max: {max}")
        
        f, Pxx = welch(data, fs, window='hamming', nperseg=1024, noverlap=512)
        
        plt.semilogy(f, Pxx)
        plt.title(f'Channel {ch+1} - Power Spectral Density')
        plt.xlabel('Frequency [Hz]')
        plt.ylabel('PSD [V^2/Hz]')
        plt.savefig(f'channel_{ch+1}_psd.png', dpi=150)
        
        userInput = input("Do you want to see the next channel? (y/n): ")
        while userInput.lower() != 'y':
            userInput = input() 

        plt.close() 
    


if __name__ == "__main__":
    main()