import type {
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MonitoringChartEvidence,
} from "@/types/monitoring";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import {
  buildThresholdRegions,
  getDetectionValueBounds,
  type DetectionTimeValue,
  type DetectionValueBounds,
  type ThresholdRegion,
} from "@/lib/telemetry-thresholds";

export type DetectionPane = "static" | "adaptive";

export interface ChartDetector {
  id: string;
  serviceId: string;
  trackerId?: string;
  name: string;
  pane: DetectionPane;
}

export interface DetectionObservation {
  sequenceNumber: number;
  timeMs: number;
  value: number | null;
  threshold: number | null;
  alarmActive: boolean;
  logValue: number | null;
  isInfinite: boolean;
  inputTimestamps?: Readonly<Record<string, string>>;
  alarmFired?: boolean;
}

export interface TelemetryChartDetector extends ChartDetector {
  observations: readonly DetectionObservation[];
}

export interface DetectionChartPoint {
  value: DetectionTimeValue;
  observation?: DetectionObservation;
}

export interface DetectionOverflow {
  observation: DetectionObservation;
  boundary: "upper" | "lower";
}

export interface SecondaryChartSeries extends ChartDetector {
  data: DetectionChartPoint[];
  thresholdRegions: ThresholdRegion[];
  overflow: DetectionOverflow[];
  latestObservation: DetectionObservation;
  bounds: DetectionValueBounds;
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

const isEvaluatedObservation = (observation: DetectionObservation, pane: DetectionPane): boolean =>
  observation.value !== null || (pane === "static" && (observation.isInfinite || observation.logValue !== null));

export const getDefaultDetectorId = (
  detectors: readonly ChartDetector[],
  pane: DetectionPane,
): string | undefined => {
  const candidates = detectors.filter((detector) => detector.pane === pane).sort((left, right) => left.id.localeCompare(right.id));
  return (candidates.find((detector) => detector.trackerId === "primary") ?? candidates[0])?.id;
};

/** Normalize loaded detector observations once, independently of the displayed range or selection. */
export const collectTelemetryChartDetectors = ({
  evidence,
  telemetryType,
  telemetryTimes,
}: {
  evidence: readonly MonitoringChartEvidence[];
  telemetryType: string;
  telemetryTimes: readonly number[];
}): TelemetryChartDetector[] => {
  const times = new Set(telemetryTimes);
  const ordered = evidence.map((item) => ({ item, time: getEvidenceTimeForSensor(item, telemetryType) }))
    .filter((entry): entry is { item: MonitoringChartEvidence; time: number } =>
      entry.time !== undefined && times.has(entry.time) && entry.item.sensor_set.includes(telemetryType));
  return collectChartDetectors(ordered);
};

/** A multivariate result belongs to the aligned observation, not to any one input. */
export const collectMonitoringChartDetectors = (evidence: readonly MonitoringChartEvidence[]): TelemetryChartDetector[] =>
  collectChartDetectors(evidence.map(item => ({ item, time: Date.parse(item.timestamp) }))
    .filter(({ time }) => Number.isFinite(time)), true);

function collectChartDetectors(
  rows: Array<{ item: MonitoringChartEvidence; time: number }>,
  includeInputs = false,
): TelemetryChartDetector[] {
  const groups = new Map<string, ChartDetector & { observations: DetectionObservation[] }>();
  const ordered = rows.sort((left, right) => left.time - right.time || left.item.sequence_number - right.item.sequence_number);
  for (const { item, time } of ordered) {
    if (item.strategy === "adaptive_stream") {
      const id = `adaptive-score:${item.service_id}`;
      const group = groups.get(id) ?? { id, serviceId: item.service_id, name: "Anomaly score", pane: "adaptive", observations: [] };
      group.observations.push({
        sequenceNumber: item.sequence_number, timeMs: time, value: finiteOrNull(item.anomaly_score),
        threshold: finiteOrNull(item.threshold), alarmActive: item.alarm, logValue: null, isInfinite: false,
        ...(includeInputs ? { inputTimestamps: item.input_timestamps, alarmFired: item.alarm } : {}),
      });
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
        sequenceNumber: item.sequence_number, timeMs: time, value: finiteOrNull(tracker.statistic_value),
        threshold: threshold !== null && threshold > 0 ? threshold : null,
        alarmActive: tracker.alarm_active, logValue: finiteOrNull(tracker.log_statistic_value),
        isInfinite: tracker.statistic_is_infinite,
        ...(includeInputs ? { inputTimestamps: item.input_timestamps,
          alarmFired: "alarm_fired" in tracker ? tracker.alarm_fired : item.alarm } : {}),
      });
      groups.set(id, group);
    }
  }
  // Buffered or wholly unavailable observations cannot create a detector choice.
  return [...groups.values()]
    .filter((group) => group.observations.some((observation) => isEvaluatedObservation(observation, group.pane)))
    .sort((left, right) => left.id.localeCompare(right.id));
}

const getOverflowBoundary = (
  observation: DetectionObservation,
  pane: DetectionPane,
): DetectionOverflow["boundary"] | undefined => {
  if (pane !== "static") return undefined;
  if (observation.isInfinite) return "upper";
  if (observation.value === null && observation.logValue !== null) {
    return observation.logValue >= 0 ? "upper" : "lower";
  }
  return observation.value !== null && observation.value <= 0 ? "lower" : undefined;
};

/** Build presentation only for chosen detectors at the displayed telemetry samples. */
export const buildSelectedDetectorSeries = ({
  detectors,
  telemetryTimes,
  selectedDetectorIds = {},
  range = {},
}: {
  detectors: readonly TelemetryChartDetector[];
  telemetryTimes: readonly number[];
  selectedDetectorIds?: SelectedDetectorIds;
  range?: { fromMs?: number; toMs?: number };
}): SecondaryChartSeries[] => {
  const times = new Set(telemetryTimes);
  return (["static", "adaptive"] as const).flatMap((pane) => {
    const id = selectedDetectorIds[pane] ?? getDefaultDetectorId(detectors, pane);
    const detector = detectors.find((candidate) => candidate.id === id && candidate.pane === pane);
    if (!detector) return [];
    const observations = detector.observations.filter((observation) => times.has(observation.timeMs));
    const latestObservation = observations[observations.length - 1];
    if (!latestObservation || !observations.some((observation) => isEvaluatedObservation(observation, pane))) return [];

    const overflow: DetectionOverflow[] = [];
    const data: DetectionChartPoint[] = observations.map((observation) => {
      const boundary = getOverflowBoundary(observation, pane);
      if (boundary) overflow.push({ observation, boundary });
      return { value: [observation.timeMs, boundary ? null : observation.value], observation };
    });
    const scoredTimes = new Set(observations.map(({ timeMs }) => timeMs));
    for (const time of times) {
      if (!scoredTimes.has(time)) data.push({ value: [time, null] });
    }
    data.sort((left, right) => left.value[0] - right.value[0]);
    const thresholds: DetectionTimeValue[] = observations.map((observation) => [
      observation.timeMs,
      isEvaluatedObservation(observation, pane) ? observation.threshold : null,
    ]);
    return [{
      id: detector.id, serviceId: detector.serviceId, trackerId: detector.trackerId, name: detector.name, pane,
      data, overflow, latestObservation,
      thresholdRegions: buildThresholdRegions(thresholds, telemetryTimes, range),
      bounds: getDetectionValueBounds(pane === "static" ? "log" : "linear", data.map(({ value }) => value), thresholds),
    }];
  });
};
