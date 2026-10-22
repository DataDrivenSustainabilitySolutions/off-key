import type { MartingaleTrackerResult, MonitoringChartEvidence } from "@/types/monitoring";

/** A static-baseline tracker that has tested once and stays below its threshold. */
export const trackerResult = (overrides: Partial<MartingaleTrackerResult> = {}): MartingaleTrackerResult => {
  const value = overrides.statistic_value === undefined ? 2 : overrides.statistic_value;
  return {
    tracker_id: "primary", betting_function: "power", betting_parameters: {}, alarm_statistic: "restarted_martingale",
    statistic_value: value, statistic_is_infinite: false, log_statistic_value: value === null ? null : Math.log(value),
    statistics: {}, e_value: 1, e_value_is_infinite: false, log_e_value: 0, threshold: 100,
    alarm_fired: false, alarm_active: false, alarm_count: 0, tested_count: 1,
    ...overrides,
  };
};

/** One evidence row; callers pass the service, time and every value they assert on. */
export const chartEvidence = (
  overrides: Partial<MonitoringChartEvidence> & Pick<MonitoringChartEvidence, "service_id" | "timestamp">,
): MonitoringChartEvidence => ({
  sequence_number: 1, sensor_set: ["L1"], input_timestamps: { L1: overrides.timestamp },
  restarted_martingale: null, threshold: 100, alarm: false, created: overrides.timestamp,
  ...overrides,
});
