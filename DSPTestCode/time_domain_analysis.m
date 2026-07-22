clear; clc; close all;

%% Time-Domain Feature Analysis for Pipe Leak Detection

%% Load dummy signals
load('large_dummy_pipe_dataset.mat');

% Find first moderate leak example
idx = find(labels == "moderate_leak",1);

x = signals(idx,:);
signal_name = char(labels(idx));

%% Remove DC offset
x = x - mean(x);

%% Optional frequency-domain band limiting, no toolbox required
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

%% Time-domain features
rms_value = sqrt(mean(x_filt.^2));
variance_value = var(x_filt);
std_value = std(x_filt);
mean_abs_value = mean(abs(x_filt));
peak_value = max(abs(x_filt));
peak_to_peak_value = max(x_filt) - min(x_filt);
crest_factor = peak_value / rms_value;

%% Zero-crossing rate
zero_crossings = sum(abs(diff(sign(x_filt)))) / 2;
zero_crossing_rate = zero_crossings / length(x_filt);

%% Simple decision logic
rms_threshold = 0.060;
variance_threshold = 0.003;

if rms_value > rms_threshold && variance_value > variance_threshold
    decision = "Possible leak detected";
else
    decision = "Normal condition";
end

%% Display results
fprintf('\nTime-Domain Analysis Results\n');
fprintf('----------------------------\n');
fprintf('Signal analyzed: %s\n', signal_name);
fprintf('RMS value: %.5f\n', rms_value);
fprintf('Variance: %.6f\n', variance_value);
fprintf('Standard deviation: %.5f\n', std_value);
fprintf('Mean absolute value: %.5f\n', mean_abs_value);
fprintf('Peak amplitude: %.5f\n', peak_value);
fprintf('Peak-to-peak amplitude: %.5f\n', peak_to_peak_value);
fprintf('Crest factor: %.4f\n', crest_factor);
fprintf('Zero-crossing rate: %.6f\n', zero_crossing_rate);
fprintf('Decision: %s\n', decision);

%% Plot filtered time-domain signal
figure;
plot(t, x_filt);
title(['Filtered Time-Domain Signal: ', signal_name]);
xlabel('Time (s)');
ylabel('Amplitude');
grid on;

%% Bar plot of selected features
features = [rms_value, variance_value, mean_abs_value, peak_value, crest_factor];
feature_names = {'RMS', 'Variance', 'Mean Abs', 'Peak', 'Crest Factor'};

figure;
bar(features);
set(gca, 'XTickLabel', feature_names);
title(['Time-Domain Features: ', signal_name]);
ylabel('Feature Value');
grid on;