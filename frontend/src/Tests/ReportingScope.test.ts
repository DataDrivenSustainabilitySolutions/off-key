// @vitest-environment node
import { describe, expect, it } from "vitest";
import { filterSourceReports } from "@/features/workspace/reporting-scope";
import type { Anomaly } from "@/types/charger";
import type { SystemRuntime } from "@/features/catalogue/systemTypes";

const runtime: SystemRuntime = { mode: "configured_only", message: "", bindings: Object.fromEntries([
  ["temperature", "accepted-a", "temperature-key"], ["pressure", "accepted-a", "pressure-key"], ["remote", "accepted-b", "temperature-key"],
].map(([id, entity_id, telemetry_key]) => [id, { entity_id, telemetry_key, connection_id: "broker", accepted_topic: "telemetry/" + entity_id + "/" + telemetry_key,
  policy: { mode: "off", interval_seconds: 10 } }])) };
const report = (anomaly_id: string, charger_id = "accepted-a", telemetry_type = "temperature-key", sensor_set?: string[]): Anomaly => ({
  anomaly_id, charger_id, telemetry_type, sensor_set, timestamp: "2026-10-15T10:00:00Z", anomaly_type: "change", anomaly_value: .01, value_type: "tail_pvalue",
});

describe("reporting source scope", () => {
  const reports = [report("temperature"), report("pressure", "accepted-a", "pressure-key"), report("remote", "accepted-b"),
    report("multi", "accepted-a", "__multivariate__", ["temperature-key", "pressure-key"]), report("legacy-multi", "accepted-a", "__multivariate__")];
  it("keeps all events in the unscoped view and none for an empty or unknown source", () => {
    expect(filterSourceReports(reports, undefined)).toBe(reports);
    expect(filterSourceReports(reports, [], runtime)).toEqual([]);
    expect(filterSourceReports(reports, ["deleted"], runtime)).toEqual([]);
    expect(filterSourceReports(reports, ["temperature"])).toEqual([]);
  });
  it("matches both runtime entity and reading, including multivariate participants", () => {
    expect(filterSourceReports(reports, ["temperature"], runtime).map(row => row.anomaly_id)).toEqual(["temperature", "multi"]);
    expect(filterSourceReports(reports, ["remote"], runtime).map(row => row.anomaly_id)).toEqual(["remote"]);
  });
  it("includes legacy multivariate events only when the entire runtime entity is selected", () => {
    expect(filterSourceReports(reports, ["temperature", "pressure"], runtime).map(row => row.anomaly_id))
      .toEqual(["temperature", "pressure", "multi", "legacy-multi"]);
  });
});
