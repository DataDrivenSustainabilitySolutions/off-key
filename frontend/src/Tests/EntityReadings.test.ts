// @vitest-environment node
import { describe, expect, it } from "vitest";

import { alarmsByReading, MULTIVARIATE_TELEMETRY_TYPE } from "../lib/anomaly-utils";
import { entityReadings } from "../features/workspace/reporting-scope";
import { createEmptySystem } from "../domain/system/systemDocument";
import type { Anomaly } from "../types/charger";
import type { SystemDocument, SystemRuntime } from "../types/system";

const reading = (id: string, deviceId?: string) => ({
  id, label: id, broker_id: "broker", topic: `site/${id}`, value_type: "number" as const, category: "Other",
  ...(deviceId && { device_id: deviceId }),
});
const document: SystemDocument = {
  ...createEmptySystem(),
  readings: [reading("flow", "pump"), reading("pressure", "pump"), reading("outside"), reading("wind")],
};
const runtime = { bindings: {
  flow: { entity_id: "entity-pump", telemetry_key: "key-flow" },
  pressure: { entity_id: "entity-pump", telemetry_key: "key-pressure" },
  outside: { entity_id: "entity-broker", telemetry_key: "key-outside" },
  wind: { entity_id: "entity-broker", telemetry_key: "key-wind" },
} } as unknown as SystemRuntime;

describe("readings of a recorded entity", () => {
  it("asks for a device's evidence by the device", () => {
    const { readings, readingByKey, evidenceScope } = entityReadings(document, runtime, "entity-pump");
    expect(readings.map(stream => stream.id)).toEqual(["flow", "pressure"]);
    expect([...readingByKey]).toEqual([["key-flow", "flow"], ["key-pressure", "pressure"]]);
    expect(evidenceScope).toEqual({ deviceId: "pump" });
  });

  it("names each reading of a broker without a device", () => {
    expect(entityReadings(document, runtime, "entity-broker").evidenceScope).toEqual({ readingIds: ["outside", "wind"] });
    expect(entityReadings(document, runtime, "unknown").evidenceScope).toEqual({ readingIds: [] });
  });

  it("names alarms by catalogue reading and keeps what the catalogue lacks", () => {
    const alarm: Anomaly = {
      anomaly_id: "a", charger_id: "entity-pump", timestamp: "2026-11-06T12:00:00Z", telemetry_type: MULTIVARIATE_TELEMETRY_TYPE,
      anomaly_type: "ml_conformal_static_multivariate", anomaly_value: 0.01, value_type: "conformal_pvalue",
      sensor_set: ["key-flow", "key-gone"],
    };
    const { readingByKey } = entityReadings(document, runtime, "entity-pump");
    expect(alarmsByReading([alarm, { ...alarm, telemetry_type: "key-pressure", sensor_set: null }], readingByKey)).toEqual([
      { ...alarm, sensor_set: ["flow", "key-gone"] },
      { ...alarm, telemetry_type: "pressure", sensor_set: null },
    ]);
  });
});
