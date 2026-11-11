import type { MonitoringChartEvidence, MonitoringIssuedForecast } from "@/types/monitoring";
import type { FutureForecastPoint } from "./forecast-future";
import { epochMilliseconds } from "@/lib/timestamps";
import { getPauseLimit } from "./telemetry-data";

export type ForecastValue = [time: number, expected: number | null, lower: number | null, upper: number | null];
export interface ForecastObservation {
  time: number;
  evaluationTime: number;
  observed: number | null;
  expected: number;
  lower: number | null;
  upper: number | null;
  alarm: boolean;
}
export interface ForecastEvidenceSeries {
  id: string;
  detectorId: string;
  inputId: string;
  name: string;
  lead: number | null;
  readingId?: string;
  slot: string | null;
  issued?: MonitoringIssuedForecast | null;
  future?: FutureForecastPoint[];
  data: Array<{ value: ForecastValue; forecastObservation?: ForecastObservation }>;
}

export const leadLabel = (lead: number | null) => lead === null ? "Lead not recorded" : `${lead} ${lead === 1 ? "update" : "updates"} ahead`;
export const forecastLeadKey = (lead: number | null) => lead === null ? "unknown" : String(lead);
/** Preserve narrow intervals on signals such as mains frequency. */
export const formatForecastValue = (value: number) => String(Number(value.toPrecision(8)));
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Keep each detector/target/lead separate and retain only its newest issuance.
 * Evaluated predictions stay historical; future points need explicit target times. */
export function buildForecastEvidence(
  rows: readonly MonitoringChartEvidence[],
  bindings: Readonly<Record<string, string>> = {},
): ForecastEvidenceSeries[] {
  const timed = rows.map(row => ({ row, time: epochMilliseconds(row.timestamp) }))
    .filter(item => Number.isFinite(item.time))
    .sort((a, b) => a.time - b.time || a.row.sequence_number - b.row.sequence_number);
  const pause = getPauseLimit(timed.map(item => item.time));
  const series = new Map<string, ForecastEvidenceSeries>();
  let previous: number | undefined;
  for (const { row, time } of timed) {
    const seen = new Set<string>();
    for (const forecast of row.forecasts ?? []) {
      if (!finite(forecast.expected)) continue;
      const id = JSON.stringify([forecast.detector_id, forecast.target, forecast.slot, forecast.lead]);
      if (seen.has(id)) continue;
      const inputs = row.detector_inputs?.find(input => input.detector_id === forecast.detector_id)
        ?? (row.detector_inputs?.length === 1 && row.detector_inputs[0]?.detector_id === null ? row.detector_inputs[0] : undefined);
      const readingId = forecast.slot ? bindings[forecast.slot] : undefined;
      // Raw forecasts belong at the exact input time, even for skewed observations.
      const targetTime = readingId ? epochMilliseconds(row.input_timestamps[readingId] ?? "") : time;
      if (!Number.isFinite(targetTime)) continue;
      seen.add(id);
      let line = series.get(id);
      if (!line) {
        line = { id, detectorId: forecast.detector_id, inputId: `input:${inputs ? inputs.detector_id ?? "" : forecast.detector_id}:${forecast.target}`,
          name: `${forecast.target} · ${forecast.detector_id} · ${leadLabel(forecast.lead)}`,
          lead: forecast.lead, readingId, slot: forecast.slot, data: [] };
        series.set(id, line);
      }
      const bounded = finite(forecast.lower) && finite(forecast.upper) && forecast.lower <= forecast.upper;
      line.issued = forecast.issued ?? null;
      const observed = inputs?.inputs[forecast.target];
      const observation: ForecastObservation = { time: targetTime, evaluationTime: time, expected: forecast.expected,
        observed: finite(observed) ? observed : null,
        lower: bounded ? forecast.lower : null, upper: bounded ? forecast.upper : null, alarm: row.alarm };
      if (previous !== undefined && time - previous > pause && line.data.length) {
        line.data.push({ value: [(line.data[line.data.length - 1]!.value[0] + targetTime) / 2, null, null, null] });
      }
      // Repeated aligned observations can reuse an input; retain the last evaluation.
      if (line.data[line.data.length - 1]?.value[0] === targetTime) line.data.pop();
      line.data.push({ value: [targetTime, forecast.expected, observation.lower, observation.upper], forecastObservation: observation });
    }
    for (const line of series.values()) {
      if (!seen.has(line.id)) {
        line.data.push({ value: [time, null, null, null] });
        line.issued = null;
      }
    }
    previous = time;
  }
  return [...series.values()].sort((a, b) => (a.lead ?? Infinity) - (b.lead ?? Infinity) || a.id.localeCompare(b.id));
}

export const latestForecast = (series: ForecastEvidenceSeries) => series.data[series.data.length - 1]?.forecastObservation;

export function intervalStatus(point: ForecastObservation): string {
  if (point.lower === null || point.upper === null) return "Interval unavailable";
  if (point.observed === null) return "Observed value unavailable";
  return point.observed < point.lower || point.observed > point.upper ? "Outside interval" : "Within interval";
}
