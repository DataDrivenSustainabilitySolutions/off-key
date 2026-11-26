import { forecastLeadKey, leadLabel, type ForecastEvidenceSeries } from "@/features/charts/forecast-evidence";

const percent = (part: number, whole: number) => `${Number((part / whole * 100).toPrecision(2))} %`;
const hasInterval = (forecasts: readonly ForecastEvidenceSeries[]) =>
  forecasts.some(forecast => forecast.data.some(point => point.value[2] !== null && point.value[3] !== null));

/** A swatch for each mark the chart draws; colours follow each reading, so they stay neutral here. */
function Swatch({ kind }: { kind: "observed" | "forecast" | "interval" }) {
  return <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
    {kind === "interval" && <rect x="1" y="2" width="20" height="8" rx="2" fill="currentColor" opacity=".2" />}
    {(kind === "observed" || kind === "forecast") && <path d="M1 6h20" stroke="currentColor" strokeWidth="2"
      strokeDasharray={kind === "forecast" ? "4 3" : undefined} />}
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

/** How often the interval held, folded away: the share at rest, the count behind it on demand. */
export function ForecastCoverage({ forecasts, coverage }: {
  forecasts: ForecastEvidenceSeries[]; coverage: { checked: number; outside: number };
}) {
  if (!hasInterval(forecasts) || !coverage.checked) return null;
  return <details className="mn-forecast-coverage">
    <summary>Coverage {percent(coverage.checked - coverage.outside, coverage.checked)}</summary>
    <p>{coverage.outside} of {coverage.checked} checked values were outside the interval. A value outside the interval is not an anomaly by itself.</p>
  </details>;
}

export function ForecastKey({ forecasts, intervalLabel }: { forecasts: ForecastEvidenceSeries[]; intervalLabel: string }) {
  return <ul className="mn-forecast-legend" aria-label="Chart key">
    <li><Swatch kind="observed" />Observed</li>
    <li><Swatch kind="forecast" />Forecast</li>
    {hasInterval(forecasts) && <li><Swatch kind="interval" />{intervalLabel}</li>}
  </ul>;
}
