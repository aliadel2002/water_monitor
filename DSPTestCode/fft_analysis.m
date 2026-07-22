clear; clc; close all;

%% FFT-Based Leak Detection Analysis

%% Load dummy signals
load('large_dummy_pipe_dataset.mat');

% Find first moderate leak example
idx = find(labels == "moderate_leak",1);

x = signals(idx,:);
signal_name = char(labels(idx));

%% Remove DC offset
x = x - mean(x);

%% Frequency-domain filtering without Signal Processing Toolbox
lowcut = 100;
highcut = 1500;

X_raw = fft(x);
f_full = (0:N-1)*(fs/N);

mask = zeros(size(f_full));

passband = (f_full >= lowcut & f_full <= highcut) | ...
           (f_full >= fs-highcut & f_full <= fs-lowcut);

mask(passband) = 1;

X_filtered = X_raw .* mask;
x_filt = real(ifft(X_filtered));

%% FFT of filtered signal
X = fft(x_filt);
f = (0:N-1)*(fs/N);

half = 1:floor(N/2);
f_half = f(half);
mag = abs(X(half))/N;

%% Frequency-domain feature extraction
leak_band = f_half >= 500 & f_half <= 1500;
total_band = f_half >= 100 & f_half <= 1500;

leak_band_energy = sum(mag(leak_band).^2);
total_energy = sum(mag(total_band).^2);
energy_ratio = leak_band_energy / total_energy;

[~, idx] = max(mag);
dominant_frequency = f_half(idx);

spectral_centroid = sum(f_half .* mag) / sum(mag);

%% Decision logic
energy_ratio_threshold = 0.55;
leak_energy_threshold = 0.00005;

if energy_ratio > energy_ratio_threshold && leak_band_energy > leak_energy_threshold
    decision = "Possible leak detected";
else
    decision = "Normal condition";
end

%% Display results
fprintf('\nFFT Analysis Results\n');
fprintf('--------------------\n');
fprintf('Signal analyzed: %s\n', signal_name);
fprintf('Leak-band energy: %.8f\n', leak_band_energy);
fprintf('Total band energy: %.8f\n', total_energy);
fprintf('Energy ratio: %.4f\n', energy_ratio);
fprintf('Dominant frequency: %.1f Hz\n', dominant_frequency);
fprintf('Spectral centroid: %.1f Hz\n', spectral_centroid);
fprintf('Decision: %s\n', decision);

%% Plot raw signal
figure;
plot(t, x);
title(['Raw Signal: ', signal_name]);
xlabel('Time (s)');
ylabel('Amplitude');
grid on;

%% Plot filtered signal
figure;
plot(t, x_filt);
title(['Filtered Signal: ', signal_name]);
xlabel('Time (s)');
ylabel('Amplitude');
grid on;

%% Plot FFT magnitude
figure;
plot(f_half, mag);
title(['FFT Magnitude Spectrum: ', signal_name]);
xlabel('Frequency (Hz)');
ylabel('Magnitude');
xlim([0 1600]);
grid on;

hold on;
xline(500, '--');
xline(1500, '--');
legend('FFT Magnitude', 'Leak Band Start', 'Leak Band End');