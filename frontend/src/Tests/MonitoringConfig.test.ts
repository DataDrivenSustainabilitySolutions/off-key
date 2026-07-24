import { describe, expect, it } from "vitest";

import {
  buildStaticMonitoringRequest,
  createDefaultStaticDraft,
  getModelDefaults,
  mqttFiltersOverlap,
} from "../pages/monitoring/config";
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
  it("detects MQTT wildcard ownership overlap", () => {
    expect(
      mqttFiltersOverlap(
        "charger/+/live-telemetry/#",
        "charger/charger-1/live-telemetry/L1",
      ),
    ).toBe(true);
    expect(
      mqttFiltersOverlap(
        "charger/charger-2/live-telemetry/L1",
        "charger/charger-1/live-telemetry/L1",
      ),
    ).toBe(false);
  });

  it("builds the complete static monitoring request", () => {
    const result = buildStaticMonitoringRequest({
      chargerId: "charger-1",
      topics: ["charger/charger-1/live-telemetry/L1"],
      draft: createDefaultStaticDraft(),
      modelDefinition,
      containerName: "radar-charger-1-test",
    });

    expect(result.errors).toEqual({});
    expect(result.request?.static_baseline_config).toMatchObject({
      training_window_size: 1200,
      calibration_window_size: 360,
      martingale_config: {
        method: "power",
        epsilon: 0.5,
        restarted_ville_threshold: 100,
      },
    });
  });

  it("rejects wildcard, cross-charger, and invalid numeric drafts", () => {
    const wildcard = buildStaticMonitoringRequest({
      chargerId: "charger-1",
      topics: ["charger/+/live-telemetry/#"],
      draft: createDefaultStaticDraft(),
      modelDefinition,
      containerName: "unused",
    });
    expect(wildcard.request).toBeUndefined();
    expect(wildcard.errors.topics).toMatch(/without MQTT wildcards/);

    const invalidDraft = {
      ...createDefaultStaticDraft(),
      trainingWindow: "1.5",
    };
    const invalid = buildStaticMonitoringRequest({
      chargerId: "charger-1",
      topics: ["charger/charger-2/live-telemetry/L1"],
      draft: invalidDraft,
      modelDefinition,
      containerName: "unused",
    });
    expect(invalid.request).toBeUndefined();
    expect(invalid.errors.topics).toMatch(/belong to charger charger-1/);
    expect(invalid.errors.trainingWindow).toBe(
      "Training samples must be an integer.",
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
