import { describe, expect, it } from "vitest";

import {
  filterAnomalies,
  MULTIVARIATE_TELEMETRY_TYPE,
} from "../lib/anomaly-utils";
import type { Anomaly } from "../types/charger";

const baseAnomaly: Anomaly = {
  anomaly_id: "anomaly-1",
  charger_id: "charger-1",
  timestamp: "2026-05-19T08:00:00.000Z",
  telemetry_type: "L1",
  anomaly_type: "ml_tailprob_univariate",
  anomaly_value: 0.004,
  value_type: "tail_pvalue",
};

describe("anomaly chart utilities", () => {
  it("includes multivariate anomalies only on involved telemetry charts", () => {
    const anomalies = [
      baseAnomaly,
      {
        ...baseAnomaly,
        anomaly_id: "anomaly-2",
        telemetry_type: MULTIVARIATE_TELEMETRY_TYPE,
        anomaly_type: "ml_conformal_static_multivariate",
        value_type: "conformal_pvalue",
        sensor_set: ["L1", "L2"],
      },
    ];

    const l1Filtered = filterAnomalies(anomalies, "L1");
    const l3Filtered = filterAnomalies(anomalies, "L3");

    expect(l1Filtered.map((anomaly) => anomaly.anomaly_id)).toEqual([
      "anomaly-1",
      "anomaly-2",
    ]);
    expect(l3Filtered).toHaveLength(0);
  });

  it("keeps legacy multivariate anomalies visible when no sensor set exists", () => {
    const anomalies = [
      {
        ...baseAnomaly,
        anomaly_id: "anomaly-legacy",
        telemetry_type: MULTIVARIATE_TELEMETRY_TYPE,
        anomaly_type: "ml_conformal_static_multivariate",
        value_type: "conformal_pvalue",
      },
    ];

    const filtered = filterAnomalies(anomalies, "L3");

    expect(filtered).toHaveLength(1);
  });
});
