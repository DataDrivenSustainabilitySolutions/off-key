// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  buildStaticMonitoringRequest,
  buildAdaptiveMonitoringRequest,
  createDefaultAdaptiveDraft,
  createDefaultStaticDraft,
  getModelDefaults,
} from "../features/monitoring/setup/config";
import type { ModelDefinition } from "../types/monitoring";

const modelDefinition: ModelDefinition = {
  strategy: "static_baseline",
  parameters: {
    required: ["n_estimators"],
    properties: {
      n_estimators: { type: "integer", minimum: 1, default: 50 },
      contamination: { type: "number", minimum: 0, maximum: 0.5 },
    },
  },
};

describe("monitoring configuration", () => {
  it("builds a strategy-discriminated adaptive request with preprocessing", () => {
    const draft = createDefaultAdaptiveDraft();
    draft.modelType = "aberrant_gadget_svm";
    draft.modelParams = { graph: { "0": [1], "1": [0] }, threshold: 0 };
    draft.scaler = "min_max_scaler";
    draft.projection = "random_projection";
    draft.projectionComponents = "2";
    const definition: ModelDefinition = {
      strategy: "adaptive_stream",
      parameters: {
        properties: {
          graph: { type: "object" },
          threshold: { type: "number" },
        },
      },
    };

    const result = buildAdaptiveMonitoringRequest({
      readingIds: ["L1", "L2"],
      draft,
      modelDefinition: definition,
      displayName: "radar-adaptive-test",
    });

    expect(result.errors).toEqual({});
    expect(result.request).toEqual({
      display_name: "radar-adaptive-test",
      reading_ids: ["L1", "L2"],
      performance_config: { hold_intervals: 3 },
      monitoring: {
        strategy: "adaptive_stream",
        model_type: "aberrant_gadget_svm",
        model_params: { graph: { "0": [1], "1": [0] }, threshold: 0 },
        training_window_size: 1200,
        calibration_window_size: 360,
        threshold_config: { mode: "calibrated_quantile", quantile: 1 },
        preprocessing_steps: [
          { type: "min_max_scaler", feature_range: [0, 1] },
          { type: "random_projection", n_components: 2, seed: 42 },
        ],
      },
    });
  });

  it("rejects a projection that exceeds the aligned feature schema", () => {
    const draft = createDefaultAdaptiveDraft();
    draft.projection = "incremental_pca";
    draft.projectionComponents = "2";
    const result = buildAdaptiveMonitoringRequest({
      readingIds: ["L1"],
      draft,
      modelDefinition: undefined,
      displayName: "unused",
    });

    expect(result.request).toBeUndefined();
    expect(result.errors.projectionComponents).toMatch(/selected readings/);
  });

  it("requires the two warm-up samples the backend requires", () => {
    const build = (trainingWindow: string) => buildAdaptiveMonitoringRequest({
      readingIds: ["L1"],
      draft: { ...createDefaultAdaptiveDraft(), trainingWindow },
      modelDefinition: undefined,
      displayName: "unused",
    });

    expect(build("1").errors.trainingWindow).toBe("Warm-up samples must be at least 2.");
    expect(build("2").errors.trainingWindow).toBeUndefined();
  });

  it("preserves explicit null adaptive model parameters", () => {
    const draft = createDefaultAdaptiveDraft();
    draft.modelType = "aberrant_x_stream";
    draft.modelParams = { max_feature_cache_size: null };
    const result = buildAdaptiveMonitoringRequest({
      readingIds: ["L1"],
      draft,
      modelDefinition: {
        strategy: "adaptive_stream",
        parameters: {
          properties: {
            max_feature_cache_size: {
              anyOf: [{ type: "integer" }, { type: "null" }],
              default: 10_000,
            },
          },
        },
      },
      displayName: "radar-adaptive-null",
    });

    expect(result.errors).toEqual({});
    expect(result.request?.monitoring.model_params.max_feature_cache_size).toBeNull();
  });

  it("builds the complete static monitoring request", () => {
    const result = buildStaticMonitoringRequest({
      readingIds: ["L1"],
      draft: createDefaultStaticDraft(),
      modelDefinition,
      displayName: "radar-charger-1-test",
    });

    expect(result.errors).toEqual({});
    expect(result.request).toMatchObject({ display_name: "radar-charger-1-test", reading_ids: ["L1"] });
    expect(result.request?.monitoring).toMatchObject({
      strategy: "static_baseline",
      training_window_size: 1200,
      calibration_window_size: 360,
      martingale_config: {
        automatic_threshold_calibration: {
          false_alarm_probability: 0.01,
          horizon: 1000,
          simulation_count: 5000,
        },
        trackers: [{
          tracker_id: "primary",
          betting_function: "power",
          alarm_statistic: "restarted_martingale",
          epsilon: 0.5,
          threshold_config: { mode: "manual", value: 100 },
        }],
      },
    });
  });

  it("builds multiple typed martingale trackers", () => {
    const draft = createDefaultStaticDraft();
    draft.martingaleTrackers = [
      draft.martingaleTrackers[0]!,
      {
        ...draft.martingaleTrackers[0]!,
        trackerId: "mixture-cusum",
        bettingFunction: "simple_mixture",
        alarmStatistic: "cusum",
        thresholdMode: "automatic",
        nGrid: "64",
        minEpsilon: "0.02",
      },
      {
        ...draft.martingaleTrackers[0]!,
        trackerId: "jumper-sr",
        bettingFunction: "simple_jumper",
        alarmStatistic: "shiryaev_roberts",
        threshold: "40",
        jump: "0.05",
      },
    ];

    const result = buildStaticMonitoringRequest({
      readingIds: ["L1"],
      draft,
      modelDefinition,
      displayName: "radar-charger-1-ensemble",
    });

    expect(result.errors).toEqual({});
    expect(
      result.request?.monitoring.martingale_config.trackers,
    ).toMatchObject([
      { tracker_id: "primary", betting_function: "power" },
      {
        tracker_id: "mixture-cusum",
        betting_function: "simple_mixture",
        alarm_statistic: "cusum",
        threshold_config: { mode: "automatic" },
        n_grid: 64,
        min_epsilon: 0.02,
      },
      {
        tracker_id: "jumper-sr",
        betting_function: "simple_jumper",
        alarm_statistic: "shiryaev_roberts",
        threshold_config: { mode: "manual", value: 40 },
        jump: 0.05,
      },
    ]);
  });

  it("requires a reading and rejects invalid numeric drafts", () => {
    const none = buildStaticMonitoringRequest({
      readingIds: [],
      draft: createDefaultStaticDraft(),
      modelDefinition,
      displayName: "unused",
    });
    expect(none.request).toBeUndefined();
    expect(none.errors.readings).toBe("Select at least one available reading.");

    const invalid = buildStaticMonitoringRequest({
      readingIds: ["L1"],
      draft: { ...createDefaultStaticDraft(), trainingWindow: "1.5" },
      modelDefinition,
      displayName: "unused",
    });
    expect(invalid.request).toBeUndefined();
    expect(invalid.errors.trainingWindow).toBe(
      "Training samples must be an integer.",
    );
  });

  it("rejects impractically large automatic threshold calibration", () => {
    const draft = createDefaultStaticDraft();
    draft.martingaleTrackers = [{
      ...draft.martingaleTrackers[0]!,
      trackerId: "oversized-mixture",
      bettingFunction: "simple_mixture",
      alarmStatistic: "cusum",
      thresholdMode: "automatic",
      nGrid: "10000",
    }];

    const result = buildStaticMonitoringRequest({
      readingIds: ["L1"],
      draft,
      modelDefinition,
      displayName: "unused",
    });

    expect(result.request).toBeUndefined();
    expect(result.errors.automaticThresholdSimulations).toMatch(
      /too large/i,
    );
  });

  it("merges registry defaults with canonical isolation-forest defaults", () => {
    expect(getModelDefaults("pyod_iforest", modelDefinition)).toEqual({
      n_estimators: 100,
      contamination: 0.1,
      random_state: 42,
    });
  });
});
