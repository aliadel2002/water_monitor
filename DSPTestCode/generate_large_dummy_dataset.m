clear; clc; close all;

%% Large Dummy Dataset Generator for Pipe Leak Detection
% Creates many simulated pipe vibration/acoustic signals for DSP testing.
% Output file: large_dummy_pipe_dataset.mat

%% Settings
fs = 3200;              % sampling frequency in Hz
T = 8;                  % seconds per sample
t = 0:1/fs:T-1/fs;
N = length(t);

rng(7);                 % repeatable random data

%% Dataset size
num_per_class = 25;

class_names = {
    'background'
    'faucet'
    'shower'
    'toilet_flush'
    'washing_machine'
    'small_drip'
    'slow_leak'
    'moderate_leak'
    'high_flow_leak'
    'nuisance_disturbance'
};

num_classes = length(class_names);
total_samples = num_classes * num_per_class;

signals = zeros(total_samples, N);
labels = strings(total_samples, 1);

sample_index = 1;

%% Generate dataset
for c = 1:num_classes
    class_name = class_names{c};

    for k = 1:num_per_class

        % Random variation per sample
        noise_scale = 0.8 + 0.4*rand;
        freq_shift = 0.9 + 0.2*rand;
        amp_shift = 0.8 + 0.5*rand;

        % Shared background
        x = 0.015*noise_scale*randn(size(t)) ...
          + 0.018*sin(2*pi*60*t) ...
          + 0.010*sin(2*pi*120*t);

        switch class_name

            case 'background'
                x = x + 0.005*randn(size(t));

            case 'faucet'
                x = x ...
                  + amp_shift*0.035*randn(size(t)) ...
                  + amp_shift*0.045*sin(2*pi*(180*freq_shift)*t) ...
                  + amp_shift*0.030*sin(2*pi*(320*freq_shift)*t);

            case 'shower'
                x = x ...
                  + amp_shift*0.050*randn(size(t)) ...
                  + amp_shift*0.050*sin(2*pi*(220*freq_shift)*t) ...
                  + amp_shift*0.040*sin(2*pi*(430*freq_shift)*t) ...
                  + amp_shift*0.025*sin(2*pi*(700*freq_shift)*t);

            case 'toilet_flush'
                envelope = exp(-t/1.8);
                burst = amp_shift*0.16*envelope.*sin(2*pi*(260*freq_shift)*t);
                x = x + burst + 0.030*randn(size(t));

            case 'washing_machine'
                cycle = square_wave_like(t, 0.8);
                x = x ...
                  + cycle .* (amp_shift*0.070*sin(2*pi*(150*freq_shift)*t)) ...
                  + 0.035*randn(size(t));

            case 'small_drip'
                drip_interval = 0.6 + 0.4*rand;
                drip_times = 0.8:drip_interval:T-0.5;

                for d = 1:length(drip_times)
                    center = round(drip_times(d)*fs);
                    width = round((0.025 + 0.025*rand)*fs);
                    idx = max(1,center-width):min(N,center+width);
                    pulse_t = linspace(-1,1,length(idx));
                    pulse = amp_shift*0.10*exp(-pulse_t.^2/0.04);
                    x(idx) = x(idx) + pulse;
                end

            case 'slow_leak'
                x = x ...
                  + amp_shift*0.035*randn(size(t)) ...
                  + amp_shift*0.035*sin(2*pi*(520*freq_shift)*t) ...
                  + amp_shift*0.030*sin(2*pi*(780*freq_shift)*t);

            case 'moderate_leak'
                x = x ...
                  + amp_shift*0.070*randn(size(t)) ...
                  + amp_shift*0.075*sin(2*pi*(650*freq_shift)*t) ...
                  + amp_shift*0.060*sin(2*pi*(950*freq_shift)*t) ...
                  + amp_shift*0.045*sin(2*pi*(1250*freq_shift)*t);

            case 'high_flow_leak'
                x = x ...
                  + amp_shift*0.100*randn(size(t)) ...
                  + amp_shift*0.090*sin(2*pi*(500*freq_shift)*t) ...
                  + amp_shift*0.080*sin(2*pi*(850*freq_shift)*t) ...
                  + amp_shift*0.065*sin(2*pi*(1300*freq_shift)*t);

            case 'nuisance_disturbance'
                % Mostly quiet, but with random short bumps.
                num_bumps = randi([1 4]);

                for b = 1:num_bumps
                    center = randi([round(0.5*fs), round((T-0.5)*fs)]);
                    width = round((0.03 + 0.05*rand)*fs);
                    idx = max(1,center-width):min(N,center+width);
                    bump_t = linspace(-1,1,length(idx));
                    bump = amp_shift*0.20*exp(-bump_t.^2/0.08) ...
                         .* sin(2*pi*(300 + 400*rand)*bump_t);
                    x(idx) = x(idx) + bump;
                end
        end

        signals(sample_index,:) = x;
        labels(sample_index) = class_name;
        sample_index = sample_index + 1;
    end
end

%% Save dataset
save('large_dummy_pipe_dataset.mat', ...
     'signals', 'labels', 'class_names', 'fs', 'T', 't', 'N', 'num_per_class');

fprintf('\nLarge dummy dataset generated.\n');
fprintf('Total samples: %d\n', total_samples);
fprintf('Samples per class: %d\n', num_per_class);
fprintf('Saved to large_dummy_pipe_dataset.mat\n');

%% Plot one example from each class
figure;
for c = 1:num_classes
    subplot(num_classes,1,c);
    idx = find(labels == class_names{c}, 1);
    plot(t, signals(idx,:));
    ylabel(class_names{c}, 'Interpreter', 'none');
    grid on;
end
xlabel('Time (s)');
sgtitle('Example Dummy Signals From Each Class');

%% Helper function
function y = square_wave_like(t, period)
    y = double(mod(t, period) < period/2);
end