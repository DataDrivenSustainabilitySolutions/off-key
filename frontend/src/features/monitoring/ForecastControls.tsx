import { forecastLeadKey, latestForecast, leadLabel, type ForecastEvidenceSeries } from "@/features/charts/forecast-evidence";

const percent = (part: number, whole: number) => `${Number((part / whole * 100).toPrecision(2))} %`;
const figure = (value: number) => String(Number(value.toPrecision(6)));
const hasInterval = (forecasts: readonly ForecastEvidenceSeries[]) =>
  forecasts.some(forecast => forecast.data.some(point => point.value[2] !== null && point.value[3] !== null));

/** A swatch for each mark the chart draws; colours follow each reading, so they stay neutral here. */
function Swatch({ kind, color }: { kind: "observed" | "forecast" | "interval" | "outside"; color?: string }) {
  return <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
    {kind === "interval" && <rect x="1" y="2" width="20" height="8" rx="2" fill="currentColor" opacity=".2" />}
    {(kind === "observed" || kind === "forecast") && <path d="M1 6h20" stroke="currentColor" strokeWidth="2"
      strokeDasharray={kind === "forecast" ? "4 3" : undefined} />}
    {kind === "outside" && <circle cx="11" cy="6" r="4" fill="none" stroke={color ?? "currentColor"} strokeWidth="2" />}
  </svg>;
}

/** The lead on show and the two extra panes, beside the chart's zoom controls. */
export function ForecastOptions({ forecasts, lead, onLead, showResiduals, onResiduals, showScores, onScores }: {
  forecasts: ForecastEvidenceSeries[]; lead: string; onLead: (lead: string) => void;
  showResiduals: boolean; onResiduals: (show: boolean) => void; showScores: boolean; onScores: (show: boolean) => void;
}) {
  const leads = [...new Set(forecasts.map(forecast => forecast.lead))];
  return <>
    {leads.length > 1 && <select aria-label="Forecast lead" value={lead} onChange={event => onLead(event.target.value)}>
      {leads.map(value => <option key={forecastLeadKey(value)} value={forecastLeadKey(value)}>{leadLabel(value)}</option>)}
    </select>}
    <button type="button" className="ex-history-view" aria-pressed={showResiduals} onClick={() => onResiduals(!showResiduals)}>Residuals</button>
    <button type="button" className="ex-history-view" aria-pressed={showScores} onClick={() => onScores(!showScores)}>Scores</button>
  </>;
}

/** Where the reading is, where the forecast goes next, and how often values left the interval. */
export function ForecastFigures({ forecasts, coverage, unit, outsideColor }: {
  forecasts: ForecastEvidenceSeries[]; coverage: { checked: number; outside: number }; unit?: string; outsideColor?: string;
}) {
  const only = forecasts.length === 1 ? forecasts[0] : undefined;
  const observed = only && latestForecast(only)?.observed;
  const next = only?.future?.[0];
  const checked = hasInterval(forecasts) && coverage.checked > 0;
  if (observed == null && !next && !checked) return null;
  return <dl className="mn-forecast-figures">
    {observed != null && <div><dt>Observed</dt><dd>{figure(observed)}{unit && <small>{unit}</small>}</dd></div>}
    {next && <div><dt>Next forecast</dt><dd>{figure(next.expected)}{unit && <small>{unit}</small>}</dd></div>}
    {checked && <div role="status" title="Outside the interval is not an anomaly by itself.">
      <dt><Swatch kind="outside" color={outsideColor} />Outside interval</dt>
      <dd>{coverage.outside}<small>of {coverage.checked} · {percent(coverage.outside, coverage.checked)}</small></dd></div>}
  </dl>;
}

export function ForecastKey({ forecasts, intervalLabel }: { forecasts: ForecastEvidenceSeries[]; intervalLabel: string }) {
  return <ul className="mn-forecast-legend" aria-label="Chart key">
    <li><Swatch kind="observed" />Observed</li>
    <li><Swatch kind="forecast" />Forecast</li>
    {hasInterval(forecasts) && <li><Swatch kind="interval" />{intervalLabel}</li>}
  </ul>;
}
