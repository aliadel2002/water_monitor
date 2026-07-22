function filteredSignal = fft_bandpass_filter( ...
    signal, ...
    fs, ...
    frequencyBand)
%FFT_BANDPASS_FILTER
%
% Performs frequency-domain bandpass filtering without requiring the
% Signal Processing Toolbox.
%
% Inputs:
%   signal        - input time-domain signal
%   fs            - sampling frequency in Hz
%   frequencyBand - [lowFrequency highFrequency]
%
% Output:
%   filteredSignal - filtered time-domain signal

    originalShape = size(signal);

    signal = double(signal(:).');

    numberOfSamples = length(signal);

    frequencyAxis = ...
        (0:numberOfSamples - 1) * fs / numberOfSamples;

    positivePassband = ...
        frequencyAxis >= frequencyBand(1) & ...
        frequencyAxis <= frequencyBand(2);

    negativePassband = ...
        frequencyAxis >= fs - frequencyBand(2) & ...
        frequencyAxis <= fs - frequencyBand(1);

    passbandMask = ...
        positivePassband | negativePassband;

    signalSpectrum = fft(signal);

    signalSpectrum(~passbandMask) = 0;

    filteredSignal = real( ...
        ifft(signalSpectrum));

    filteredSignal = reshape( ...
        filteredSignal, ...
        originalShape);
end