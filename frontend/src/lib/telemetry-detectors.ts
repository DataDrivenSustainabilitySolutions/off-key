import type {
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MonitoringChartEvidence,
} from "@/types/monitoring";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import { buildThresholdRegions, type ThresholdRegion, type DetectionTimeValue } from "@/lib/telemetry-thresholds";

export type DetectionPane = "static" | "adaptive";

export interface ChartDetector {
  id: string;
  serviceId: string;
  trackerId?: string;
  name: string;
  pane: DetectionPane;
}

export interface DetectionObservation {
  timeMs: number;
  value: number | null;
  threshold: number | null;
  alarmActive: boolean;
  logValue: number | null;
  isInfinite: boolean;
}

export interface DetectionOverflow {
  timeMs: number;
  value: number | null;
  threshold: number | null;
  logValue: number | null;
  alarmActive: boolean;
  boundary: "upper" | "lower";
}

export interface SecondaryChartSeries extends ChartDetector {
  threshold: number | null;
  color: string;
  data: DetectionTimeValue[];
  thresholds: DetectionTimeValue[];
  thresholdRegions: ThresholdRegion[];
  overflow: DetectionOverflow[];
  observations: DetectionObservation[];
  latestObservation: DetectionObservation;
  scale: "log" | "linear";
  kind: "static_evidence" | "adaptive_score";
}

export type SelectedDetectorIds = Partial<Record<DetectionPane, string>>;

const statisticLabels: Record<MartingaleAlarmStatistic, string> = {
  martingale: "All-history martingale",
  restarted_martingale: "Restarted e-process",
  cusum: "CUSUM",
  shiryaev_roberts: "Shiryaev-Roberts",
};
const bettingLabels: Record<MartingaleBettingFunction, string> = {
  power: "Power",
  simple_mixture: "Simple mixture",
  simple_jumper: "Simple jumper",
};

const finiteOrNull = (value: number | null | undefined): number | null =>
  value != null && Number.isFinite(value) ? value : null;

const addTelemetryGaps = (points: DetectionTimeValue[], times: readonly number[]): DetectionTimeValue[] => {
  const scoredTimes = new Set(points.map(([time]) => time));
  return [...points, ...times.filter((time) => !scoredTimes.has(time)).map((time): DetectionTimeValue => [time, null])]
    .sort((left, right) => left[0] - right[0]);
};

export const getDefaultDetectorId = (
  detectors: readonly ChartDetector[],
  pane: DetectionPane,
): string | undefined => {
  const candidates = detectors.filter((detector) => detector.pane === pane).sort((left, right) => left.id.localeCompare(right.id));
  return (candidates.find((detector) => detector.trackerId === "primary") ?? candidates[0])?.id;
};

export const selectDetectorSeries = (
  series: readonly SecondaryChartSeries[],
  selected: SelectedDetectorIds = {},
): SecondaryChartSeries[] => ["static", "adaptive"].flatMap((pane) => {
  const id = selected[pane as DetectionPane] ?? getDefaultDetectorId(series, pane as DetectionPane);
  const detector = series.find((candidate) => candidate.id === id && candidate.pane === pane);
  return detector ? [detector] : [];
});

export const collectTelemetryChartDetectors = ({
  evidence,
  telemetryType,
  telemetryTimes,
  range = {},
}: {
  evidence: readonly MonitoringChartEvidence[];
  telemetryType: string;
  telemetryTimes: readonly number[];
  range?: { fromMs?: number; toMs?: number };
}): SecondaryChartSeries[] => {
  const times = new Set(telemetryTimes);
  const groups = new Map<string, ChartDetector & { observations: DetectionObservation[] }>();
  const ordered = evidence.map((item) => ({ item, time: getEvidenceTimeForSensor(item, telemetryType) }))
    .filter((entry): entry is { item: MonitoringChartEvidence; time: number } =>
      entry.time !== undefined && times.has(entry.time) && entry.item.sensor_set.includes(telemetryType))
    .sort((left, right) => left.time - right.time || left.item.sequence_number - right.item.sequence_number);
  for (const { item, time } of ordered) {
    if (item.strategy === "adaptive_stream") {
      const score = finiteOrNull(item.anomaly_score);
      const id = `adaptive-score:${item.service_id}`;
      const group = groups.get(id) ?? { id, serviceId: item.service_id, name: "Anomaly score", pane: "adaptive", observations: [] };
      group.observations.push({ timeMs: time, value: score, threshold: finiteOrNull(item.threshold), alarmActive: item.alarm, logValue: null, isInfinite: false });
      groups.set(id, group);
      continue;
    }
    const trackers = item.tracker_results?.length ? item.tracker_results : [{
      tracker_id: "primary", betting_function: "power" as const,
      alarm_statistic: "restarted_martingale" as const,
      statistic_value: item.restarted_martingale, statistic_is_infinite: false,
      log_statistic_value: null, threshold: item.threshold, alarm_active: item.alarm,
    }];
    for (const tracker of trackers) {
      const legacy = tracker.tracker_id === "primary" && tracker.betting_function === "power" && tracker.alarm_statistic === "restarted_martingale";
      const id = legacy ? `restarted-martingale:${item.service_id}` : `martingale:${item.service_id}:${tracker.tracker_id}`;
      const suffix = tracker.betting_function === "power" && tracker.tracker_id === "primary" ? "" : ` (${bettingLabels[tracker.betting_function]} · ${tracker.tracker_id})`;
      const group = groups.get(id) ?? {
        id, serviceId: item.service_id, trackerId: tracker.tracker_id,
        name: `${statisticLabels[tracker.alarm_statistic]}${suffix}`,
        pane: "static", observations: [],
      };
      const threshold = finiteOrNull(tracker.threshold);
      group.observations.push({
        timeMs: time, value: finiteOrNull(tracker.statistic_value),
        threshold: threshold !== null && threshold > 0 ? threshold : null,
        alarmActive: tracker.alarm_active, logValue: finiteOrNull(tracker.log_statistic_value),
        isInfinite: tracker.statistic_is_infinite,
      });
      groups.set(id, group);
    }
  }
  return [...groups.values()].sort((left, right) => left.id.localeCompare(right.id)).flatMap((group) => {
    const staticPane = group.pane === "static";
    const overflow: DetectionOverflow[] = [];
    const points: DetectionTimeValue[] = group.observations.map((observation) => {
      const { timeMs, value, threshold, logValue, isInfinite, alarmActive } = observation;
      if (staticPane && (isInfinite || (value === null && logValue !== null))) {
        overflow.push({ timeMs, value, threshold, logValue, alarmActive, boundary: isInfinite || (logValue !== null && logValue >= 0) ? "upper" : "lower" });
        return [timeMs, null];
      }
      if (staticPane && value !== null && value <= 0) {
        overflow.push({ timeMs, value, threshold, logValue, alarmActive, boundary: "lower" });
        return [timeMs, null];
      }
      return [timeMs, value];
    });
    // Buffered or wholly unavailable observations cannot create a detector choice.
    if (!points.some(([, value]) => value !== null) && overflow.length === 0) return [];
    const thresholds = addTelemetryGaps(group.observations.map((observation) => [
      observation.timeMs,
      observation.value !== null || (staticPane && (observation.isInfinite || observation.logValue !== null))
        ? observation.threshold : null,
    ]), telemetryTimes);
    const latestObservation = group.observations[group.observations.length - 1];
    if (!latestObservation) return [];
    return [{
      id: group.id, serviceId: group.serviceId, trackerId: group.trackerId, name: group.name, pane: group.pane,
      threshold: latestObservation.threshold,
      color: staticPane ? "#059669" : "#7c3aed",
      data: addTelemetryGaps(points, telemetryTimes), thresholds,
      thresholdRegions: buildThresholdRegions(thresholds, telemetryTimes, range),
      overflow, observations: group.observations, latestObservation,
      scale: staticPane ? "log" : "linear",
      kind: staticPane ? "static_evidence" : "adaptive_score",
    }];
  });
};
