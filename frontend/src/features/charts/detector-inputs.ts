import type { MonitoringChartEvidence } from "@/types/monitoring";
import { getPauseLimit } from "./telemetry-data";

/** What a forecaster step expected of a feature at one time, and the interval around it. */
export type ForecastPoint = [time: number, expected: number | null, lower: number | null, upper: number | null];

/** One feature a detector scored, over time. A null value breaks the line. */
export interface DetectorInputSeries {
  id: string;
  name: string;
  data: Array<[time: number, value: number | null]>;
  /** The forecast the feature was compared with, when a forecaster step scored it. */
  forecast?: ForecastPoint[];
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** The interval of a hovered forecast point, such as " (11.8 to 12.9)", or nothing without one. */
export const forecastIntervalText = (value: unknown, format: (value: number) => string): string =>
  Array.isArray(value) && finite(value[2]) && finite(value[3]) ? ` (${format(value[2])} to ${format(value[3])})` : "";

/** More lines than this stop being readable in one pane. */
export const MAX_DETECTOR_INPUT_SERIES = 8;
/**
 * The features the detectors scored, one line each, at the time of each evaluated observation.
 * These are the values after every step before the detector, such as phase deviations, so
 * they differ from the raw readings. Rows written before the service stored them have none.
 * A feature a forecaster step scored also carries the forecast made for each observation.
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
        line.data.push([time, finite(value) ? value : null]);
        seen.add(id);
      }
    }
    const forecasted = new Set<string>();
    for (const { detector_id: detectorId, target, expected, lower, upper } of row.forecasts ?? []) {
      // A service with one detector stores its inputs without the detector's id.
      const line = series.get(`input:${detectorId}:${target}`) ?? series.get(`input::${target}`);
      if (!line || forecasted.has(line.id) || !finite(expected)) continue;
      line.forecast ??= [];
      if (broken && line.forecast.length) line.forecast.push([(previous! + time) / 2, null, null, null]);
      const bounded = finite(lower) && finite(upper) && lower <= upper;
      line.forecast.push([time, expected, bounded ? lower : null, bounded ? upper : null]);
      forecasted.add(line.id);
    }
    // A feature the observation did not carry leaves a gap instead of a line across it.
    for (const line of series.values()) {
      if (!seen.has(line.id) && line.data.length) line.data.push([time, null]);
      if (!forecasted.has(line.id) && line.forecast?.length) line.forecast.push([time, null, null, null]);
    }
    previous = time;
  }
  return [...series.values()].filter((line) => line.data.some(([, value]) => value !== null));
};
