import type { MonitoringIssuedForecast } from "@/types/monitoring";
import { epochMilliseconds } from "@/lib/timestamps";

export type ForecastView = "overlay" | "ahead" | "data";
export const FORECAST_VIEWS: readonly ForecastView[] = ["overlay", "ahead", "data"];
export const FORECAST_VIEW_LABELS: Record<ForecastView, string> = {
  overlay: "Overlay", ahead: "Forecast ahead", data: "Data only",
};
export const nextForecastView = (view: ForecastView): ForecastView =>
  FORECAST_VIEWS[(FORECAST_VIEWS.indexOf(view) + 1) % FORECAST_VIEWS.length]!;

export interface FutureForecastPoint {
  time: number;
  originTime: number;
  issuedAt: number;
  lead: number;
  expected: number;
  lower: number | null;
  upper: number | null;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Use persisted target times, never shift evaluated predictions into the future.
 * The latest issuance replaces older ones even when unavailable or untimed. */
export function futureForecastPoints(issued: MonitoringIssuedForecast | null | undefined,
  observedThrough: number, calibratedLead: number | null): FutureForecastPoint[] {
  if (issued?.time_basis !== "estimated_cadence" || !Array.isArray(issued.points)) return [];
  const originTime = epochMilliseconds(issued.origin_time ?? "");
  const issuedAt = epochMilliseconds(issued.issued_at);
  if (!Number.isFinite(originTime) || !Number.isFinite(issuedAt) || originTime > observedThrough) return [];
  const seen = new Set<number>();
  return issued.points.flatMap(point => {
    const time = epochMilliseconds(point.target_time ?? "");
    if (!Number.isFinite(time) || time <= observedThrough || !finite(point.expected)
      || !Number.isInteger(point.lead) || point.lead < 1 || seen.has(time)) return [];
    seen.add(time);
    const bounded = point.lead === calibratedLead && finite(point.lower) && finite(point.upper) && point.lower <= point.upper;
    return [{ time, originTime, issuedAt, lead: point.lead, expected: point.expected,
      lower: bounded ? point.lower : null, upper: bounded ? point.upper : null }];
  }).sort((a, b) => a.time - b.time);
}
