clear; clc; close all;

%% Cross-Correlation Full Algorithm for Pipe Leak Detection
% This script demonstrates two-sensor normalized cross-correlation.
% It estimates signal similarity and time delay between two vibration sensors.

%% Load dataset
load('large_dummy_pipe_dataset.mat');

%% Select one leak-like signal from the dataset
idx = find(labels == "moderate_leak", 1);
base_signal = signals(idx,:);

%% Sampling information
% fs, t, N are loaded from the dataset

%% Create simulated two-sensor case
% Sensor B receives a delayed and slightly noisier version of Sensor A.
known_delay_seconds = 0.0035;
known_delay_samples = round(known_delay_seconds * fs);

sensorA = base_signal + 0.02*randn(size(base_signal));

sensorB = [zeros(1, known_delay_samples), ...
           base_signal(1:end-known_delay_samples)] ...
           + 0.02*randn(size(base_signal));

%% Step 1: Remove DC offset
x = sensorA - mean(sensorA);
y = sensorB - mean(sensorB);

%% Step 2: Bandpass filter using FFT-domain filtering
lowcut = 100;
highcut = 1500;

f_full = (0:N-1)*(fs/N);

mask = zeros(size(f_full));

passband = (f_full >= lowcut & f_full <= highcut) | ...
           (f_full >= fs-highcut & f_full <= fs-lowcut);

mask(passband) = 1;

X = fft(x);
Y = fft(y);

x_filt = real(ifft(X .* mask));
y_filt = real(ifft(Y .* mask));

%% Step 3: Normalize signals
x_norm = x_filt / max(abs(x_filt));
y_norm = y_filt / max(abs(y_filt));

%% Step 4: Full-signal normalized cross-correlation
[c, lags] = xcorr(x_norm, y_norm, 'coeff');

[max_corr, idx_max] = max(c);
lag_samples = lags(idx_max);
estimated_delay_seconds = lag_samples / fs;

%% Step 5: Decision logic
correlation_threshold = 0.60;

if max_corr > correlation_threshold
    decision = "Similar vibration detected at both sensors";
else
    decision = "Low similarity between sensors";
end

%% Display full-signal results
fprintf('\nFull-Signal Cross-Correlation Results\n');
fprintf('=====================================\n');
fprintf('Known delay: %.6f seconds (%d samples)\n', ...
    known_delay_seconds, known_delay_samples);
fprintf('Estimated delay: %.6f seconds (%d samples)\n', ...
    estimated_delay_seconds, lag_samples);
fprintf('Maximum correlation: %.4f\n', max_corr);
fprintf('Decision: %s\n', decision);

%% Step 6: Windowed cross-correlation
window_seconds = 1.0;
window_N = round(window_seconds * fs);
num_windows = floor(N / window_N);

window_corr = zeros(1, num_windows);
window_delay = zeros(1, num_windows);

for k = 1:num_windows

    start_idx = (k-1)*window_N + 1;
    end_idx = k*window_N;

    xw = x_norm(start_idx:end_idx);
    yw = y_norm(start_idx:end_idx);

    [cw, lw] = xcorr(xw, yw, 'coeff');

    [window_corr(k), idx_win] = max(cw);
    window_delay(k) = lw(idx_win) / fs;
end

correlation_persistence = sum(window_corr > correlation_threshold) / num_windows;

fprintf('\nWindowed Cross-Correlation Results\n');
fprintf('==================================\n');
fprintf('Window length: %.2f seconds\n', window_seconds);
fprintf('Number of windows: %d\n', num_windows);
fprintf('Correlation persistence score: %.3f\n', correlation_persistence);

if correlation_persistence > 0.60
    fprintf('Windowed decision: Persistent shared vibration pattern detected.\n');
else
    fprintf('Windowed decision: Shared pattern is not persistent.\n');
end

%% Plot sensor signals
figure;
plot(t, x_norm);
title('Sensor A Filtered and Normalized Signal');
xlabel('Time (s)');
ylabel('Normalized Amplitude');
grid on;

figure;
plot(t, y_norm);
title('Sensor B Filtered and Normalized Signal');
xlabel('Time (s)');
ylabel('Normalized Amplitude');
grid on;

%% Plot full cross-correlation
figure;
plot(lags/fs, c, 'LineWidth', 1.2);
title('Full-Signal Normalized Cross-Correlation');
xlabel('Lag (seconds)');
ylabel('Correlation Coefficient');
grid on;
hold on;
xline(estimated_delay_seconds, '--', 'Estimated Delay');
legend('Cross-Correlation', 'Estimated Delay');

%% Plot windowed correlation values
figure;
bar(window_corr);
title('Windowed Maximum Correlation');
xlabel('Window Number');
ylabel('Maximum Correlation');
grid on;
yline(correlation_threshold, '--', 'Threshold');

%% Plot estimated delay per window
figure;
plot(window_delay, '-o', 'LineWidth', 1.2);
title('Estimated Delay Per Window');
xlabel('Window Number');
ylabel('Estimated Delay (seconds)');
grid on;