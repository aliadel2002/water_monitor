clear;
clc;
close all;

%% PIPE LEAK DETECTION WORKFLOW
%
% This script:
% 1. Loads the simulated pipe dataset.
% 2. Separates the data into training and testing sets.
% 3. Extracts time-domain and frequency-domain features.
% 4. Calculates explicit thresholds using training data.
% 5. Classifies each signal using feature voting and persistence.
% 6. Reports test accuracy, sensitivity, specificity, and precision.
% 7. Demonstrates two-sensor cross-correlation.
%
% Required files:
%   large_dummy_pipe_dataset.mat
%   extract_pipe_features.m
%   fft_bandpass_filter.m
%   calibrate_thresholds.m
%   classify_pipe_signal.m
%   normalized_lag_correlation.m
%   plot_signal_diagnostics.m

%% User-adjustable settings

datasetFile = 'large_dummy_pipe_dataset.mat';

% Main analysis frequency range
settings.analysisBandHz = [100 1500];

% Initial candidate leak-frequency range
settings.leakBandHz = [500 1500];

% Windowing settings
settings.windowSeconds = 1.0;
settings.windowOverlap = 0.50;

% A sustained leak requires this fraction of windows to be positive
settings.minimumPersistence = 0.60;

% Percentage of data used to calculate thresholds
settings.trainingFraction = 0.70;

% Makes train/test split repeatable
settings.randomSeed = 12;

% Classes treated as leaks
settings.leakClasses = [
    "small_drip"
    "slow_leak"
    "moderate_leak"
    "high_flow_leak"
];

% Cross-correlation settings
settings.correlationThreshold = 0.70;
settings.maximumLagSeconds = 0.020;

rng(settings.randomSeed);

%% Load dataset

if ~isfile(datasetFile)
    error(['Could not find ', datasetFile, ...
        '. Place the dataset in the same folder as this script.']);
end

dataset = load(datasetFile);

requiredVariables = {'signals', 'labels', 'fs'};

for k = 1:length(requiredVariables)
    variableName = requiredVariables{k};

    if ~isfield(dataset, variableName)
        error('Dataset is missing required variable: %s', variableName);
    end
end

signals = double(dataset.signals);
labels = string(dataset.labels(:));
fs = double(dataset.fs);

numberOfSignals = size(signals, 1);
samplesPerSignal = size(signals, 2);

if numberOfSignals ~= length(labels)
    error('The number of signal rows does not match the number of labels.');
end

fprintf('\n');
fprintf('PIPE LEAK DETECTION WORKFLOW\n');
fprintf('============================\n');
fprintf('Total signals: %d\n', numberOfSignals);
fprintf('Samples per signal: %d\n', samplesPerSignal);
fprintf('Sampling frequency: %.1f Hz\n', fs);
fprintf('Window duration: %.2f seconds\n', settings.windowSeconds);
fprintf('Window overlap: %.0f percent\n', ...
    settings.windowOverlap * 100);

%% Create stratified training and testing split

[trainingIndices, testingIndices] = stratified_split( ...
    labels, ...
    settings.trainingFraction, ...
    settings.randomSeed);

fprintf('Training signals: %d\n', sum(trainingIndices));
fprintf('Testing signals: %d\n', sum(testingIndices));

%% Extract features from all signals

fprintf('\nExtracting signal features...\n');

featureRecords = repmat(empty_feature_record(), numberOfSignals, 1);
windowFeatureTables = cell(numberOfSignals, 1);

for signalIndex = 1:numberOfSignals

    currentSignal = signals(signalIndex, :);

    [featureRecords(signalIndex), windowFeatureTables{signalIndex}] = ...
        extract_pipe_features( ...
            currentSignal, ...
            fs, ...
            settings);
end

featureTable = struct2table(featureRecords);

featureTable.Label = labels;

featureTable.IsLeak = ismember( ...
    labels, ...
    settings.leakClasses);

%% Calculate thresholds using training data only

trainingFeatureTable = featureTable(trainingIndices, :);

thresholds = calibrate_thresholds( ...
    trainingFeatureTable, ...
    settings);

fprintf('\n');
fprintf('CALIBRATED DECISION THRESHOLDS\n');
fprintf('==============================\n');
fprintf('RMS threshold: %.6f\n', thresholds.rms);
fprintf('Leak-band energy-ratio threshold: %.4f\n', ...
    thresholds.energyRatio);
fprintf('Spectral-centroid threshold: %.2f Hz\n', ...
    thresholds.spectralCentroid);
fprintf('Minimum positive features per window: %d of 3\n', ...
    thresholds.minimumFeatureVotes);
fprintf('Minimum persistence: %.2f\n', ...
    thresholds.minimumPersistence);
fprintf('Two-sensor correlation threshold: %.2f\n', ...
    settings.correlationThreshold);

%% Classify every signal

classificationRecords = repmat( ...
    empty_result_record(), ...
    numberOfSignals, ...
    1);

for signalIndex = 1:numberOfSignals

    currentWindowFeatures = windowFeatureTables{signalIndex};

    classificationRecords(signalIndex) = classify_pipe_signal( ...
        currentWindowFeatures, ...
        thresholds);
end

classificationTable = struct2table(classificationRecords);

classificationTable.Label = labels;

classificationTable.TrueLeak = ismember( ...
    labels, ...
    settings.leakClasses);

classificationTable.Split = repmat( ...
    "Training", ...
    numberOfSignals, ...
    1);

classificationTable.Split(testingIndices) = "Testing";

classificationTable = movevars( ...
    classificationTable, ...
    {'Label', 'Split', 'TrueLeak'}, ...
    'Before', ...
    1);

%% Evaluate held-out testing data

testingResults = classificationTable(testingIndices, :);

trueClass = testingResults.TrueLeak;
predictedClass = testingResults.PredictedLeak;

truePositives = sum(predictedClass & trueClass);
trueNegatives = sum(~predictedClass & ~trueClass);
falsePositives = sum(predictedClass & ~trueClass);
falseNegatives = sum(~predictedClass & trueClass);

sensitivity = safe_divide( ...
    truePositives, ...
    truePositives + falseNegatives);

specificity = safe_divide( ...
    trueNegatives, ...
    trueNegatives + falsePositives);

precision = safe_divide( ...
    truePositives, ...
    truePositives + falsePositives);

accuracy = safe_divide( ...
    truePositives + trueNegatives, ...
    length(trueClass));

balancedAccuracy = mean([sensitivity, specificity]);

fprintf('\n');
fprintf('HELD-OUT TEST PERFORMANCE\n');
fprintf('=========================\n');
fprintf('True positives: %d\n', truePositives);
fprintf('True negatives: %d\n', trueNegatives);
fprintf('False positives: %d\n', falsePositives);
fprintf('False negatives: %d\n', falseNegatives);
fprintf('Sensitivity: %.3f\n', sensitivity);
fprintf('Specificity: %.3f\n', specificity);
fprintf('Precision: %.3f\n', precision);
fprintf('Accuracy: %.3f\n', accuracy);
fprintf('Balanced accuracy: %.3f\n', balancedAccuracy);

%% Create per-class summary

uniqueClasses = unique(labels, 'stable');

classSummary = table();

for classIndex = 1:length(uniqueClasses)

    currentClass = uniqueClasses(classIndex);

    currentMask = testingIndices & labels == currentClass;

    if ~any(currentMask)
        continue;
    end

    numberOfTestSignals = sum(currentMask);

    leakDecisionRate = mean( ...
        classificationTable.PredictedLeak(currentMask));

    averagePersistence = mean( ...
        classificationTable.Persistence(currentMask));

    averageVoteCount = mean( ...
        classificationTable.MeanVoteCount(currentMask));

    newRow = table( ...
        currentClass, ...
        numberOfTestSignals, ...
        leakDecisionRate, ...
        averagePersistence, ...
        averageVoteCount, ...
        'VariableNames', { ...
            'Class', ...
            'NumberOfTestSignals', ...
            'LeakDecisionRate', ...
            'AveragePersistence', ...
            'AverageVoteCount'});

    classSummary = [classSummary; newRow];
end

fprintf('\n');
fprintf('PER-CLASS TEST SUMMARY\n');
fprintf('======================\n');

disp(classSummary);

%% Save numerical results

writetable( ...
    featureTable, ...
    'extracted_feature_summary.csv');

writetable( ...
    classificationTable, ...
    'classification_results.csv');

writetable( ...
    classSummary, ...
    'per_class_test_summary.csv');

save( ...
    'calibrated_thresholds.mat', ...
    'thresholds', ...
    'settings');

fprintf('\nSaved output files:\n');
fprintf('extracted_feature_summary.csv\n');
fprintf('classification_results.csv\n');
fprintf('per_class_test_summary.csv\n');
fprintf('calibrated_thresholds.mat\n');

%% Plot feature distributions and thresholds

figure('Name', 'Calibrated Feature Thresholds');

subplot(3, 1, 1);

boxchart( ...
    categorical(featureTable.Label), ...
    featureTable.MeanRMS);

hold on;

yline( ...
    thresholds.rms, ...
    '--', ...
    'RMS Threshold');

ylabel('Mean Window RMS');
title('RMS by Signal Class');
grid on;

subplot(3, 1, 2);

boxchart( ...
    categorical(featureTable.Label), ...
    featureTable.MeanEnergyRatio);

hold on;

yline( ...
    thresholds.energyRatio, ...
    '--', ...
    'Energy-Ratio Threshold');

ylabel('Leak-Band Energy Ratio');
title('Leak-Band Energy Ratio by Signal Class');
grid on;

subplot(3, 1, 3);

boxchart( ...
    categorical(featureTable.Label), ...
    featureTable.MeanSpectralCentroid);

hold on;

yline( ...
    thresholds.spectralCentroid, ...
    '--', ...
    'Spectral-Centroid Threshold');

ylabel('Spectral Centroid (Hz)');
title('Spectral Centroid by Signal Class');
grid on;
xtickangle(30);

%% Plot confusion matrix

figure('Name', 'Held-Out Confusion Matrix');

confusionValues = [
    trueNegatives, falsePositives
    falseNegatives, truePositives
];

imagesc(confusionValues);

axis equal;
axis tight;
colorbar;

xticks([1 2]);
xticklabels({'Predicted Normal', 'Predicted Leak'});

yticks([1 2]);
yticklabels({'True Normal', 'True Leak'});

title('Held-Out Test Confusion Matrix');

for row = 1:2
    for column = 1:2

        text( ...
            column, ...
            row, ...
            num2str(confusionValues(row, column)), ...
            'HorizontalAlignment', ...
            'center', ...
            'FontWeight', ...
            'bold');
    end
end

%% Plot persistence by class

figure('Name', 'Leak Detection Persistence');

boxchart( ...
    categorical(classificationTable.Label(testingIndices)), ...
    classificationTable.Persistence(testingIndices));

hold on;

yline( ...
    thresholds.minimumPersistence, ...
    '--', ...
    'Persistence Threshold');

ylabel('Fraction of Positive Windows');
title('Windowed Leak-Feature Persistence');
grid on;
xtickangle(30);

%% Plot one example signal

exampleIndex = find( ...
    testingIndices & labels == "moderate_leak", ...
    1);

if isempty(exampleIndex)
    exampleIndex = find(testingIndices, 1);
end

plot_signal_diagnostics( ...
    signals(exampleIndex, :), ...
    fs, ...
    labels(exampleIndex), ...
    windowFeatureTables{exampleIndex}, ...
    thresholds, ...
    settings);

%% Two-sensor cross-correlation demonstration

% Sensor B is created as a delayed and slightly noisier version of Sensor A.

knownDelaySeconds = 0.0035;

knownDelaySamples = round( ...
    knownDelaySeconds * fs);

baseSignal = signals(exampleIndex, :);

sensorA = baseSignal + ...
    0.01 * randn(size(baseSignal));

sensorB = [
    zeros(1, knownDelaySamples), ...
    baseSignal(1:end-knownDelaySamples)
];

sensorB = sensorB + ...
    0.015 * randn(size(sensorB));

[
    peakCorrelation, ...
    estimatedLagSamples, ...
    correlationLags, ...
    correlationValues ...
] = normalized_lag_correlation( ...
    sensorA, ...
    sensorB, ...
    fs, ...
    settings.analysisBandHz, ...
    settings.maximumLagSeconds);

estimatedDelaySeconds = estimatedLagSamples / fs;

sharedEventConfirmed = ...
    peakCorrelation >= settings.correlationThreshold;

fprintf('\n');
fprintf('TWO-SENSOR CORRELATION EXAMPLE\n');
fprintf('==============================\n');
fprintf('Known delay: %.6f seconds\n', knownDelaySeconds);
fprintf('Estimated delay: %.6f seconds\n', ...
    estimatedDelaySeconds);
fprintf('Peak correlation: %.4f\n', peakCorrelation);
fprintf('Correlation threshold: %.2f\n', ...
    settings.correlationThreshold);
fprintf('Shared event confirmed: %s\n', ...
    string(sharedEventConfirmed));

figure('Name', 'Two-Sensor Cross-Correlation');

plot( ...
    correlationLags / fs, ...
    correlationValues, ...
    'LineWidth', ...
    1.1);

hold on;

xline( ...
    estimatedDelaySeconds, ...
    '--', ...
    'Estimated Delay');

yline( ...
    settings.correlationThreshold, ...
    '--', ...
    'Correlation Threshold');

xlabel('Lag (seconds)');
ylabel('Normalized Correlation');
title('Two-Sensor Event Confirmation');
grid on;

%% Local helper functions

function [trainingIndices, testingIndices] = stratified_split( ...
    labels, ...
    trainingFraction, ...
    randomSeed)

    rng(randomSeed);

    labels = string(labels(:));

    trainingIndices = false(size(labels));
    testingIndices = false(size(labels));

    uniqueClasses = unique(labels, 'stable');

    for classIndex = 1:length(uniqueClasses)

        currentClass = uniqueClasses(classIndex);

        classIndices = find(labels == currentClass);

        classIndices = classIndices( ...
            randperm(length(classIndices)));

        numberTraining = round( ...
            trainingFraction * length(classIndices));

        numberTraining = max( ...
            1, ...
            min(length(classIndices) - 1, numberTraining));

        trainingIndices( ...
            classIndices(1:numberTraining)) = true;

        testingIndices( ...
            classIndices(numberTraining + 1:end)) = true;
    end
end

function value = safe_divide(numerator, denominator)

    if denominator == 0
        value = NaN;
    else
        value = numerator / denominator;
    end
end

function record = empty_feature_record()

    record = struct( ...
        'MeanRMS', NaN, ...
        'StandardDeviationRMS', NaN, ...
        'MeanVariance', NaN, ...
        'MeanAbsoluteValue', NaN, ...
        'MeanCrestFactor', NaN, ...
        'MeanZeroCrossingRate', NaN, ...
        'MeanEnergyRatio', NaN, ...
        'MeanSpectralCentroid', NaN, ...
        'MeanDominantFrequency', NaN, ...
        'NumberOfWindows', 0);
end

function record = empty_result_record()

    record = struct( ...
        'PredictedLeak', false, ...
        'Classification', "Unclassified", ...
        'Persistence', NaN, ...
        'MeanVoteCount', NaN, ...
        'MaximumVoteCount', NaN, ...
        'RMSFlagRate', NaN, ...
        'EnergyFlagRate', NaN, ...
        'SpectralCentroidFlagRate', NaN);
end