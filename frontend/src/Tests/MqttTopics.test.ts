// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  buildDeviceTelemetryTopic,
  parseDeviceTelemetryTopic,
} from "../lib/mqtt-topics";

describe("canonical device telemetry topics", () => {
  it("builds the canonical concrete topic", () => {
    expect(buildDeviceTelemetryTopic("0", "voltageAc3")).toBe(
      "telemetry/0/voltageAc3",
    );
  });

  it.each([
    "voltageAc3",
    "voltageAc",
    "currentDc",
    "voltageAc2",
    "voltageAc1",
  ])("parses charger zero sensor %s", (telemetryType) => {
    expect(
      parseDeviceTelemetryTopic(`telemetry/0/${telemetryType}`),
    ).toEqual({ chargerId: "0", telemetryType });
  });

  it("preserves hierarchical telemetry tails", () => {
    expect(parseDeviceTelemetryTopic("telemetry/a/phase/ac/voltage")).toEqual(
      { chargerId: "a", telemetryType: "phase/ac/voltage" },
    );
  });

  it.each([
    "charger/0/live-telemetry/voltageAc",
    "device/charger/0/voltageAc",
    "telemetry/0",
    "telemetry/0/",
    "telemetry/+/voltageAc",
    "telemetry/0/#",
    "telemetry/charger+1/voltageAc",
    "telemetry/charger#1/voltageAc",
    "telemetry/0/voltage+Ac",
    "telemetry/0/voltage#Ac",
  ])("rejects non-canonical or non-concrete topic %s", (topic) => {
    expect(parseDeviceTelemetryTopic(topic)).toBeNull();
  });

  it("refuses to construct topics containing embedded MQTT wildcards", () => {
    expect(() => buildDeviceTelemetryTopic("charger+1", "voltageAc")).toThrow();
    expect(() => buildDeviceTelemetryTopic("0", "voltage#Ac")).toThrow();
  });
});
