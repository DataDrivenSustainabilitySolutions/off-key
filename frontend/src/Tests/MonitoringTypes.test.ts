import { describe, expect, it } from "vitest";

import {
  getOperationalStageDisplay,
  getServiceDeleteActionDisplay,
  getStatusDisplay,
} from "../types/monitoring";
import type { ActiveService, OperationalStage } from "../types/monitoring";

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

describe("service delete action display", () => {
  const baseService: ActiveService = {
    id: "svc-1",
    container_id: "ctr-1",
    container_name: "radar-charger-1",
    mqtt_topics: ["charger/charger-1/live-telemetry/sine"],
    status: true,
    operational_status: {
      stage: "operational",
      message_count: 0,
      processed_message_count: 0,
      is_stale: false,
    },
  };

  it("uses stop-and-delete copy for running services", () => {
    const action = getServiceDeleteActionDisplay({
      ...baseService,
      docker_status: "running",
    });

    expect(action.confirmation).toBe(
      'Stop and delete service "radar-charger-1"?'
    );
    expect(action.ariaLabel).toBe("stop and delete service");
  });

  it("uses record-delete copy for terminal service rows", () => {
    const action = getServiceDeleteActionDisplay({
      ...baseService,
      status: false,
      docker_status: "not_found",
    });

    expect(action.confirmation).toBe('Delete service record "radar-charger-1"?');
    expect(action.ariaLabel).toBe("delete service record");
  });
});
