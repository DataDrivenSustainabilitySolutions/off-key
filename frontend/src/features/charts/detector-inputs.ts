import type { MonitoringChartEvidence } from "@/types/monitoring";
import { getPauseLimit } from "./telemetry-data";

/** One feature a detector scored, over time. A null value breaks the line. */
export interface DetectorInputSeries {
  id: string;
  name: string;
  data: Array<[time: number, value: number | null]>;
}

/** More lines than this stop being readable in one pane. */
export const MAX_DETECTOR_INPUT_SERIES = 8;
/**
 * The features the detectors scored, one line each, at the time of each evaluated observation.
 * These are the values after every step before the detector, such as phase deviations, so
 * they differ from the raw readings. Rows written before the service stored them have none.
 */
export const buildDetectorInputSeries = (
  rows: readonly MonitoringChartEvidence[],
  timeOf: (row: MonitoringChartEvidence) => number | undefined,
  window?: readonly [startMs: number, endMs: number],
): DetectorInputSeries[] => {
  const timed = rows.flatMap((row) => {
    const time = timeOf(row);
    return row.detector_inputs?.length && time !== undefined && Number.isFinite(time)
      && (!window || (time >= window[0] && time <= window[1])) ? [{ row, time }] : [];
  }).sort((left, right) => left.time - right.time || left.row.sequence_number - right.row.sequence_number);
  if (!timed.length) return [];
  const breakAfter = getPauseLimit(timed.map(({ time }) => time));
  const series = new Map<string, DetectorInputSeries>();
  let previous: number | undefined;
  for (const { row, time } of timed) {
    if (time === previous) continue;
    const broken = previous !== undefined && time - previous > breakAfter;
    const seen = new Set<string>();
    for (const { detector_id: detectorId, inputs } of row.detector_inputs ?? []) {
      for (const [feature, value] of Object.entries(inputs ?? {})) {
        const id = `input:${detectorId ?? ""}:${feature}`;
        let line = series.get(id);
        if (!line) {
          if (series.size >= MAX_DETECTOR_INPUT_SERIES) continue;
          line = { id, name: detectorId ? `${detectorId} · ${feature}` : feature, data: [] };
          series.set(id, line);
        }
        if (broken && line.data.length) line.data.push([(previous! + time) / 2, null]);
        line.data.push([time, typeof value === "number" && Number.isFinite(value) ? value : null]);
        seen.add(id);
      }
    }
    // A feature the observation did not carry leaves a gap instead of a line across it.
    for (const line of series.values()) if (!seen.has(line.id) && line.data.length) line.data.push([time, null]);
    previous = time;
  }
  return [...series.values()].filter((line) => line.data.some(([, value]) => value !== null));
};
