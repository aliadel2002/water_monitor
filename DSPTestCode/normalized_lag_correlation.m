function [ ...
    peakCorrelation, ...
    estimatedLagSamples, ...
    lagValues, ...
    correlationValues ...
] = normalized_lag_correlation( ...
    sensorA, ...
    sensorB, ...
    fs, ...
    analysisBandHz, ...
    maximumLagSeconds)
%NORMALIZED_LAG_CORRELATION
%
% Calculates normalized cross-correlation between two pipe sensors.
%
% This function:
% 1. Removes DC offset.
% 2. Bandpass filters both signals.
% 3. Tests correlation over a limited lag range.
% 4. Returns the strongest correlation and corresponding delay.
%
% No Signal Processing Toolbox is required.

    sensorA = double(sensorA(:).');

    sensorB = double(sensorB(:).');

    %% Make both signals the same length

    commonLength = min( ...
        length(sensorA), ...
        length(sensorB));

    sensorA = sensorA(1:commonLength);

    sensorB = sensorB(1:commonLength);

    %% Remove DC offset

    sensorA = sensorA - mean(sensorA);

    sensorB = sensorB - mean(sensorB);

    %% Bandpass filter

    sensorA = fft_bandpass_filter( ...
        sensorA, ...
        fs, ...
        analysisBandHz);

    sensorB = fft_bandpass_filter( ...
        sensorB, ...
        fs, ...
        analysisBandHz);

    %% Normalize overall energy

    sensorA = sensorA / ...
        max(sqrt(sum(sensorA.^2)), eps);

    sensorB = sensorB / ...
        max(sqrt(sum(sensorB.^2)), eps);

    %% Define allowed lag range

    maximumLagSamples = round( ...
        maximumLagSeconds * fs);

    maximumLagSamples = min( ...
        maximumLagSamples, ...
        commonLength - 1);

    lagValues = ...
        -maximumLagSamples:maximumLagSamples;

    correlationValues = zeros(size(lagValues));

    %% Calculate normalized correlation at every lag

    for lagIndex = 1:length(lagValues)

        currentLag = lagValues(lagIndex);

        if currentLag >= 0

            shortenedSensorA = ...
                sensorA(1:end-currentLag);

            shortenedSensorB = ...
                sensorB(1+currentLag:end);

        else

            positiveShift = -currentLag;

            shortenedSensorA = ...
                sensorA(1+positiveShift:end);

            shortenedSensorB = ...
                sensorB(1:end-positiveShift);
        end

        shortenedSensorA = ...
            shortenedSensorA - mean(shortenedSensorA);

        shortenedSensorB = ...
            shortenedSensorB - mean(shortenedSensorB);

        denominator = sqrt( ...
            sum(shortenedSensorA.^2) * ...
            sum(shortenedSensorB.^2));

        correlationValues(lagIndex) = ...
            sum(shortenedSensorA .* shortenedSensorB) / ...
            max(denominator, eps);
    end

    %% Find strongest correlation

    [peakCorrelation, maximumIndex] = ...
        max(correlationValues);

    estimatedLagSamples = ...
        lagValues(maximumIndex);
end