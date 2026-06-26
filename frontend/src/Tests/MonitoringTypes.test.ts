import { describe, expect, it } from "vitest";

import {
  getOperationalStageDisplay,
  getStatusDisplay,
} from "../types/monitoring";
import type { OperationalStage } from "../types/monitoring";

describe("monitoring status display", () => {
  it("shows exited workloads as neutral until exit codes are available", () => {
    const status = getStatusDisplay("exited", true);

    expect(status.label).toBe("Exited");
    expect(status.className).toContain("yellow");
  });

  it("shows restarting workloads as transient", () => {
    const status = getStatusDisplay("restarting", true);

    expect(status.label).toBe("Restarting");
    expect(status.className).toContain("yellow");
  });

  it("shows explicitly stopped workloads as stopped", () => {
    const status = getStatusDisplay("stopped", false);

    expect(status.label).toBe("Stopped");
    expect(status.className).toContain("gray");
  });
});

describe("operational stage display", () => {
  it.each<[OperationalStage, string, string]>([
    ["starting", "Starting", "yellow"],
    ["waiting_for_data", "Waiting for data", "yellow"],
    ["collecting_training", "Collecting training data", "sky"],
    ["collecting_calibration", "Calibrating", "blue"],
    ["training", "Training", "blue"],
    ["operational", "Operational", "green"],
    ["degraded", "Degraded", "yellow"],
    ["failed", "Failed", "red"],
    ["stopped", "Stopped", "gray"],
  ])("maps %s to display metadata", (stage, label, color) => {
    const status = getOperationalStageDisplay({
      stage,
      message_count: 0,
      processed_message_count: 0,
      is_stale: false,
    });

    expect(status.label).toBe(label);
    expect(status.className).toContain(color);
  });
});
