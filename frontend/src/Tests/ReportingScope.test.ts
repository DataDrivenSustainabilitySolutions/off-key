// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatAlarmReadings, isAlarmContext } from "../lib/anomaly-utils";
import {
  alarmSource, detailsHref, selectedSource, sourceLabel, sourceReadings,
} from "../features/workspace/reporting-scope";
import { createEmptySystem } from "../domain/system/systemDocument";
import type { SystemDocument } from "../types/system";
import { alarm } from "./support/fixtures/monitoring";

const reading = (id: string, deviceId?: string) => ({
  id, label: id, broker_id: "broker", topic: `site/${id}`, value_type: "number" as const, category: "Other",
  ...(deviceId && { device_id: deviceId }),
});
const document: SystemDocument = {
  ...createEmptySystem(),
  brokers: [{ id: "broker", label: "Plant MQTT", host: "mqtt", port: 1883, tls: false }] as SystemDocument["brokers"],
  devices: [{ id: "pump", label: "Pump" }] as SystemDocument["devices"],
  readings: [reading("flow", "pump"), reading("pressure", "pump"), reading("outside"), reading("wind")],
};

describe("readings of a device or broker", () => {
  it("asks for a device's alarms and evidence by the device", () => {
    const { readings, scope } = sourceReadings(document, { kind: "device", id: "pump" });
    expect(readings.map(stream => stream.id)).toEqual(["flow", "pressure"]);
    expect(scope).toEqual({ deviceId: "pump" });
    expect(sourceLabel(document, { kind: "device", id: "pump" })).toBe("Pump");
  });

  it("names each reading of a broker without a device", () => {
    expect(sourceReadings(document, { kind: "broker", id: "broker" }).scope).toEqual({ readingIds: ["outside", "wind"] });
    expect(sourceReadings(document, { kind: "broker", id: "unknown" }).scope).toEqual({ readingIds: [] });
    expect(sourceLabel(document, { kind: "broker", id: "broker" })).toBe("Plant MQTT");
    expect(sourceLabel(document, { kind: "device", id: "gone" })).toBeUndefined();
  });

  it("links devices and brokers to their own details pages", () => {
    expect(detailsHref({ kind: "device", id: "pump/1" })).toBe("/details/pump%2F1");
    expect(detailsHref({ kind: "broker", id: "broker" })).toBe("/details/broker/broker");
  });

  it("finds where an alarm's readings come from", () => {
    expect(alarmSource(alarm({ device_id: "pump" }), document)).toEqual({ kind: "device", id: "pump" });
    expect(alarmSource(alarm({ device_id: null, reading_ids: ["wind"] }), document)).toEqual({ kind: "broker", id: "broker" });
    expect(alarmSource(alarm({ device_id: null, reading_ids: [] }), document)).toBeUndefined();
  });

  it("scopes a selection to one source only when it has exactly one", () => {
    expect(selectedSource(["flow", "pressure"], document)).toEqual({ kind: "device", id: "pump" });
    expect(selectedSource(["outside"], document)).toEqual({ kind: "broker", id: "broker" });
    expect(selectedSource(["flow", "wind"], document)).toBeUndefined();
    expect(selectedSource(undefined, document)).toBeUndefined();
  });
});

describe("alarm readings", () => {
  it("names readings by catalogue label, or says the monitor did not record them", () => {
    const named = alarm({ reading_ids: ["flow", "pressure"], reading_labels: { flow: "Flow", pressure: "Pressure" }, multivariate: true });
    expect(formatAlarmReadings(named)).toBe("Flow, Pressure");
    expect(formatAlarmReadings(alarm({ reading_ids: [], multivariate: true }))).toBe("not recorded");
    expect(isAlarmContext(named)).toBe(true);
    expect(isAlarmContext(alarm())).toBe(false);
  });
});
