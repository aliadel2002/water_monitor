function thresholds = calibrate_thresholds( ...
    trainingTable, ...
    settings)
%CALIBRATE_THRESHOLDS
%
% Calculates explicit feature thresholds using labeled training data.
%
% The selected threshold maximizes balanced classification accuracy on the
% training set.
%
% The held-out testing data is not used during threshold selection.

    requiredVariables = {
        'MeanRMS'
        'MeanEnergyRatio'
        'MeanSpectralCentroid'
        'IsLeak'
    };

    for variableIndex = 1:length(requiredVariables)

        variableName = requiredVariables{variableIndex};

        if ~ismember( ...
                variableName, ...
                trainingTable.Properties.VariableNames)

            error( ...
                'Training table is missing variable: %s', ...
                variableName);
        end
    end

    trueLeakLabels = logical( ...
        trainingTable.IsLeak);

    %% Calculate best RMS threshold

    thresholds.rms = find_best_threshold( ...
        trainingTable.MeanRMS, ...
        trueLeakLabels);

    %% Calculate best energy-ratio threshold

    thresholds.energyRatio = find_best_threshold( ...
        trainingTable.MeanEnergyRatio, ...
        trueLeakLabels);

    %% Calculate best spectral-centroid threshold

    thresholds.spectralCentroid = find_best_threshold( ...
        trainingTable.MeanSpectralCentroid, ...
        trueLeakLabels);

    %% Decision-rule settings

    thresholds.minimumFeatureVotes = 2;

    thresholds.minimumPersistence = ...
        settings.minimumPersistence;
end

function bestThreshold = find_best_threshold( ...
    featureValues, ...
    trueLeakLabels)
%FIND_BEST_THRESHOLD
%
% Tests possible thresholds and selects the threshold that maximizes
% balanced accuracy.
%
% A feature value greater than or equal to the threshold is treated as a
% positive leak indicator.

    featureValues = double(featureValues(:));

    trueLeakLabels = logical(trueLeakLabels(:));

    validValues = isfinite(featureValues);

    featureValues = featureValues(validValues);

    trueLeakLabels = trueLeakLabels(validValues);

    sortedUniqueValues = unique( ...
        sort(featureValues));

    if isempty(sortedUniqueValues)
        error('No valid feature values were available.');
    end

    if length(sortedUniqueValues) == 1
        bestThreshold = sortedUniqueValues(1);
        return;
    end

    midpointThresholds = ...
        (sortedUniqueValues(1:end-1) + ...
        sortedUniqueValues(2:end)) / 2;

    candidateThresholds = [
        sortedUniqueValues(1) - eps(sortedUniqueValues(1))
        midpointThresholds
        sortedUniqueValues(end) + eps(sortedUniqueValues(end))
    ];

    bestBalancedAccuracy = -Inf;

    bestFalsePositiveRate = Inf;

    bestThreshold = candidateThresholds(1);

    for candidateIndex = 1:length(candidateThresholds)

        currentThreshold = ...
            candidateThresholds(candidateIndex);

        predictedLeak = ...
            featureValues >= currentThreshold;

        truePositives = sum( ...
            predictedLeak & trueLeakLabels);

        trueNegatives = sum( ...
            ~predictedLeak & ~trueLeakLabels);

        falsePositives = sum( ...
            predictedLeak & ~trueLeakLabels);

        falseNegatives = sum( ...
            ~predictedLeak & trueLeakLabels);

        sensitivity = safe_ratio( ...
            truePositives, ...
            truePositives + falseNegatives);

        specificity = safe_ratio( ...
            trueNegatives, ...
            trueNegatives + falsePositives);

        balancedAccuracy = mean( ...
            [sensitivity, specificity]);

        falsePositiveRate = 1 - specificity;

        isBetterAccuracy = ...
            balancedAccuracy > bestBalancedAccuracy;

        isTieWithLowerFalsePositiveRate = ...
            abs(balancedAccuracy - bestBalancedAccuracy) < 1e-12 && ...
            falsePositiveRate < bestFalsePositiveRate;

        if isBetterAccuracy || isTieWithLowerFalsePositiveRate

            bestBalancedAccuracy = balancedAccuracy;

            bestFalsePositiveRate = falsePositiveRate;

            bestThreshold = currentThreshold;
        end
    end
end

function result = safe_ratio(numerator, denominator)

    if denominator == 0
        result = 0;
    else
        result = numerator / denominator;
    end
end