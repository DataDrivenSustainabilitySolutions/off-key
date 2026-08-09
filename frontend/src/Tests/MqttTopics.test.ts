import { describe, expect, it } from "vitest";

import {
  buildDeviceTelemetryChargerFilter,
  buildDeviceTelemetryTopic,
  DEVICE_TELEMETRY_FILTER,
  parseDeviceTelemetryTopic,
} from "../lib/mqtt-topics";

describe("canonical device telemetry topics", () => {
  it("builds the canonical filter and concrete topic", () => {
    expect(DEVICE_TELEMETRY_FILTER).toBe("device/#");
    expect(buildDeviceTelemetryChargerFilter("0")).toBe(
      "device/evCharger/0/#",
    );
    expect(buildDeviceTelemetryTopic("0", "voltageAc3")).toBe(
      "device/evCharger/0/voltageAc3",
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
      parseDeviceTelemetryTopic(`device/evCharger/0/${telemetryType}`),
    ).toEqual({ chargerId: "0", telemetryType });
  });

  it("preserves hierarchical telemetry tails", () => {
    expect(parseDeviceTelemetryTopic("device/evCharger/a/phase/ac/voltage")).toEqual(
      { chargerId: "a", telemetryType: "phase/ac/voltage" },
    );
  });

  it.each([
    "charger/0/live-telemetry/voltageAc",
    "device/charger/0/voltageAc",
    "device/evCharger/0",
    "device/evCharger/0/",
    "device/evCharger/+/voltageAc",
    "device/evCharger/0/#",
    "device/evCharger/charger+1/voltageAc",
    "device/evCharger/charger#1/voltageAc",
    "device/evCharger/0/voltage+Ac",
    "device/evCharger/0/voltage#Ac",
  ])("rejects non-canonical or non-concrete topic %s", (topic) => {
    expect(parseDeviceTelemetryTopic(topic)).toBeNull();
  });

  it("refuses to construct topics containing embedded MQTT wildcards", () => {
    expect(() => buildDeviceTelemetryTopic("charger+1", "voltageAc")).toThrow();
    expect(() => buildDeviceTelemetryTopic("0", "voltage#Ac")).toThrow();
  });
});
