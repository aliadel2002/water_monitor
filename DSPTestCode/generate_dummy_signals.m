import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# -----------------------------
# 1. Settings
# -----------------------------
fs = 10000          # sampling frequency, Hz
T = 2               # duration, seconds
t = np.linspace(0, T, fs*T, endpoint=False)

# -----------------------------
# 2. Generate dummy sensor data
# -----------------------------

# Normal pipe vibration: low-amplitude background noise + low-frequency vibration
normal_signal = (
    0.05 * np.random.randn(len(t)) +
    0.08 * np.sin(2 * np.pi * 120 * t)
)

# Leak signal: normal vibration + higher-frequency leak-like tone/noise
leak_signal = (
    0.05 * np.random.randn(len(t)) +
    0.08 * np.sin(2 * np.pi * 120 * t) +
    0.25 * np.sin(2 * np.pi * 1800 * t)
)

# Choose which signal to test
signal = leak_signal

# -----------------------------
# 3. Bandpass filter
# -----------------------------
def bandpass_filter(x, lowcut, highcut, fs, order=4):
    nyq = fs / 2
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype="band")
    return filtfilt(b, a, x)

filtered_signal = bandpass_filter(signal, 500, 3000, fs)

# -----------------------------
# 4. FFT
# -----------------------------
N = len(filtered_signal)
freqs = np.fft.rfftfreq(N, 1/fs)
fft_mag = np.abs(np.fft.rfft(filtered_signal)) / N

# -----------------------------
# 5. Feature extraction
# -----------------------------
rms = np.sqrt(np.mean(filtered_signal**2))

leak_band = (freqs >= 1000) & (freqs <= 2500)
leak_band_energy = np.sum(fft_mag[leak_band]**2)

dominant_freq = freqs[np.argmax(fft_mag)]

# -----------------------------
# 6. Simple leak decision
# -----------------------------
rms_threshold = 0.08
energy_threshold = 0.0005

if rms > rms_threshold and leak_band_energy > energy_threshold:
    decision = "Possible leak detected"
else:
    decision = "Normal condition"

# -----------------------------
# 7. Print results
# -----------------------------
print("DSP Feature Results")
print("-------------------")
print(f"RMS amplitude: {rms:.4f}")
print(f"Leak-band energy: {leak_band_energy:.6f}")
print(f"Dominant frequency: {dominant_freq:.1f} Hz")
print(f"Decision: {decision}")

# -----------------------------
# 8. Plot results
# -----------------------------
plt.figure()
plt.plot(t, signal)
plt.title("Raw Dummy Sensor Signal")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude")
plt.grid(True)
plt.show()

plt.figure()
plt.plot(t, filtered_signal)
plt.title("Filtered Signal")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude")
plt.grid(True)
plt.show()

plt.figure()
plt.plot(freqs, fft_mag)
plt.title("FFT Magnitude Spectrum")
plt.xlabel("Frequency (Hz)")
plt.ylabel("Magnitude")
plt.xlim(0, 4000)
plt.grid(True)
plt.show()