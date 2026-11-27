import { epochMilliseconds } from "@/lib/timestamps";
import type {
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MonitoringChartEvidence,
  MonitoringDetectorResult,
} from "@/types/monitoring";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import { getPauseLimit } from "./telemetry-data";
import {
  getDetectionValueBounds,
  type DetectionTimeValue,
  type DetectionValueBounds,
} from "./telemetry-thresholds";

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
  /** The detection rule fired here and a Mute alarms step held the alarm back. */
  alarmMuted?: boolean;
  logValue: number | null;
  isInfinite: boolean;
  inputTimestamps?: Readonly<Record<string, string>>;
  alarmFired?: boolean;
  /** Each detector's part when the policy combined several. */
  detectors?: readonly MonitoringDetectorResult[];
}

export interface TelemetryChartDetector extends ChartDetector {
  observations: readonly DetectionObservation[];
}

export interface DetectionChartPoint {
  value: DetectionTimeValue;
  observation?: DetectionObservation;
  /** Set when this result stands for its interval: the highest of `count` results. */
  peak?: { count: number };
}

interface DetectionOverflow {
  observation: DetectionObservation;
  boundary: "upper" | "lower";
}

export interface SecondaryChartSeries extends ChartDetector {
  data: DetectionChartPoint[];
  overflow: DetectionOverflow[];
  latestObservation: DetectionObservation;
  bounds: DetectionValueBounds;
  /** Values are each score divided by its own threshold, so the threshold is the line at 1. */
  relative?: boolean;
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
      entry.time !== undefined && times.has(entry.time) && entry.item.reading_ids.includes(telemetryType));
  return collectChartDetectors(ordered);
};

/** A multivariate result belongs to the aligned observation, not to any one input. */
export const collectMonitoringChartDetectors = (evidence: readonly MonitoringChartEvidence[]): TelemetryChartDetector[] =>
  collectChartDetectors(evidence.map(item => ({ item, time: epochMilliseconds(item.timestamp) }))
    .filter(({ time }) => Number.isFinite(time)), true);

/** Only a muted alarm carries the mark, so other observations stay as they were. */
const muted = (held: boolean | undefined) => held ? { alarmMuted: true } : {};

/** What a tooltip says of an observation's alarm: a muted alarm is not an active one. */
export const alarmText = (observation: Pick<DetectionObservation, "alarmActive" | "alarmMuted">) =>
  observation.alarmMuted ? "muted" : observation.alarmActive ? "active" : "inactive";

function collectChartDetectors(
  rows: Array<{ item: MonitoringChartEvidence; time: number }>,
  includeInputs = false,
): TelemetryChartDetector[] {
  const groups = new Map<string, ChartDetector & { observations: DetectionObservation[] }>();
  const ordered = rows.sort((left, right) => left.time - right.time || left.item.sequence_number - right.item.sequence_number);
  for (const { item, time } of ordered) {
    if (item.strategy === "adaptive_stream") {
      const id = `adaptive-score:${item.monitor_id}`;
      const group = groups.get(id) ?? { id, serviceId: item.monitor_id, name: "Anomaly score", pane: "adaptive", observations: [] };
      group.observations.push({
        sequenceNumber: item.sequence_number, timeMs: time, value: finiteOrNull(item.anomaly_score),
        threshold: finiteOrNull(item.threshold), alarmActive: item.alarm, ...muted(item.muted), logValue: null, isInfinite: false,
        ...(includeInputs ? { inputTimestamps: item.input_timestamps, alarmFired: item.alarm,
          ...(item.detector_results?.length ? { detectors: item.detector_results } : {}) } : {}),
      });
      groups.set(id, group);
      continue;
    }
    for (const tracker of item.tracker_results ?? []) {
      const id = `martingale:${item.monitor_id}:${tracker.tracker_id}`;
      const suffix = tracker.betting_function === "power" && tracker.tracker_id === "primary" ? "" : ` (${bettingLabels[tracker.betting_function]} · ${tracker.tracker_id})`;
      const group = groups.get(id) ?? {
        id, serviceId: item.monitor_id, trackerId: tracker.tracker_id,
        name: `${statisticLabels[tracker.alarm_statistic]}${suffix}`,
        pane: "static", observations: [],
      };
      const threshold = finiteOrNull(tracker.threshold);
      group.observations.push({
        sequenceNumber: item.sequence_number, timeMs: time, value: finiteOrNull(tracker.statistic_value),
        threshold: threshold !== null && threshold > 0 ? threshold : null,
        alarmActive: tracker.alarm_active, logValue: finiteOrNull(tracker.log_statistic_value),
        ...muted(tracker.alarm_muted),
        isInfinite: tracker.statistic_is_infinite,
        ...(includeInputs ? { inputTimestamps: item.input_timestamps,
          alarmFired: tracker.alarm_fired,
          ...(item.detector_results?.length ? { detectors: item.detector_results } : {}) } : {}),
      });
      groups.set(id, group);
    }
  }
  // Buffered or wholly unavailable observations cannot create a detector choice.
  return [...groups.values()]
    .filter((group) => group.observations.some((observation) => isEvaluatedObservation(observation, group.pane)))
    .sort((left, right) => left.id.localeCompare(right.id));
}

/** Results this far under the threshold all sit on the floor of the log scale. */
const RELATIVE_FLOOR = 1 / 8;
const relativeBounds = (ratios: readonly number[]): DetectionValueBounds => ({
  // Half the threshold is low enough to see a score settle; only a real share of results lower widens the view.
  minimum: ratios.filter(ratio => ratio < 0.5).length > ratios.length * 0.05 ? 2 ** Math.floor(Math.log2(Math.min(...ratios))) : 0.5,
  maximum: 2 ** Math.ceil(Math.log2(Math.max(1.5, ...ratios) * 1.05)),
});

/** How far above the highest alarm threshold the evidence pane reaches: four decades. */
const EVIDENCE_HEADROOM = 1e4;

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
}: {
  detectors: readonly TelemetryChartDetector[];
  telemetryTimes: readonly number[];
  selectedDetectorIds?: SelectedDetectorIds;
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
    // Evidence far above the alarm threshold says no more than "alarm", so the log pane
    // stops a few decades above it and marks higher values at its top edge instead of
    // stretching the axis until the threshold sits at the bottom.
    const highest = Math.max(0, ...observations.flatMap((observation) =>
      isEvaluatedObservation(observation, pane) && observation.threshold !== null && Number.isFinite(observation.threshold)
        ? [observation.threshold] : []));
    const ceiling = pane === "static" && highest > 0 ? highest * EVIDENCE_HEADROOM : Number.POSITIVE_INFINITY;
    const data: DetectionChartPoint[] = observations.map((observation) => {
      const boundary = getOverflowBoundary(observation, pane)
        ?? (observation.value !== null && observation.value > ceiling ? "upper" : undefined);
      if (boundary) overflow.push({ observation, boundary });
      return { value: [observation.timeMs, boundary ? null : observation.value], observation };
    });
    // The line joins consecutive evaluations, so readings without a score in between, such as
    // those an observation skipped while waiting for the other inputs, do not break it into dots.
    // A pause, such as one a Gate holds back, does.
    const pauseLimit = getPauseLimit(observations.map(({ timeMs }) => timeMs));
    for (let index = data.length - 1; index > 0; index--) {
      const before = data[index - 1]!.value[0], after = data[index]!.value[0];
      if (after - before > pauseLimit) data.splice(index, 0, { value: [(before + after) / 2, null] });
    }
    // An adaptive threshold moves with every recalibration. Measured against its own threshold,
    // each score answers the one question the pane is for: how close it came to an alarm.
    const relative = pane === "adaptive" && observations.some(observation => observation.value !== null && (observation.threshold ?? 0) > 0)
      && observations.every(observation => observation.value === null || observation.threshold === null || observation.threshold > 0);
    if (relative) {
      for (const point of data) {
        const observation = point.observation;
        if (observation && point.value[1] !== null) point.value = [point.value[0],
          observation.threshold ? Math.max(RELATIVE_FLOOR, point.value[1] / observation.threshold) : null];
      }
      return [{
        id: detector.id, serviceId: detector.serviceId, trackerId: detector.trackerId, name: detector.name, pane,
        data, overflow, latestObservation, relative,
        // Half steps around what was scored, always with the threshold in view and room above the highest result.
        bounds: relativeBounds(data.flatMap(({ value }) => value[1] === null ? [] : [value[1]])),
      }];
    }
    const thresholds: DetectionTimeValue[] = observations.map((observation) => [
      observation.timeMs,
      isEvaluatedObservation(observation, pane) ? observation.threshold : null,
    ]);
    return [{
      id: detector.id, serviceId: detector.serviceId, trackerId: detector.trackerId, name: detector.name, pane,
      data, overflow, latestObservation,
      bounds: getDetectionValueBounds(pane === "static" ? "log" : "linear", data.map(({ value }) => value), thresholds),
    }];
  });
};
