import { useMemo } from "react";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import { collectTelemetryChartDetectors } from "./telemetry-detectors";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";
import { useDetectorSelection } from "./use-detector-selection";

type Options = {
  telemetryType: string;
  /** Evidence already narrowed to the chart's service. */
  evidence: readonly MonitoringChartEvidence[];
  telemetryTimes: readonly number[];
  /** Observation times that count as awaiting a score once newer than the last one. */
  pendingCandidateTimes: readonly number[];
  service?: ActiveService;
  /** Detector choices reset when this changes. */
  selectionKey: string;
  /** Count only a running service as operational. */
  requireActiveService?: boolean;
};

/** Detector panes for one reading: the detectors, the chosen one per pane and scoring progress. */
export function useDetectorPanes({ telemetryType, evidence, telemetryTimes, pendingCandidateTimes, service,
  selectionKey, requireActiveService = true }: Options) {
  const detectors = useMemo(() => collectTelemetryChartDetectors({ telemetryType, evidence, telemetryTimes }),
    [telemetryType, evidence, telemetryTimes]);
  const detectorCatalog = useMemo(() => detectors.map(({ id, serviceId, trackerId, name, pane }) =>
    ({ id, serviceId, trackerId, name, pane })), [detectors]);
  const selection = useDetectorSelection(detectorCatalog, selectionKey);
  const lastScoreTime = useMemo(() => evidence.reduce<number | undefined>((latest, item) => {
    const time = getEvidenceTimeForSensor(item, telemetryType);
    return time === undefined ? latest : Math.max(latest ?? -Infinity, time);
  }, undefined), [evidence, telemetryType]);
  const operational = Boolean((!requireActiveService || service?.status)
    && service?.operational_status.stage === "operational" && !service.operational_status.is_stale);
  const pending = useMemo(() => operational && lastScoreTime !== undefined
    ? pendingCandidateTimes.filter((time) => time > lastScoreTime) : [],
  [operational, lastScoreTime, pendingCandidateTimes]);
  const showDetectorControls = selection.controlCatalog.some((detector) =>
    selection.controlCatalog.filter((other) => other.pane === detector.pane).length > 1);
  return { detectors, ...selection, lastScoreTime, operational, awaitingFirstScore: operational && lastScoreTime === undefined,
    pending, showDetectorControls };
}
