import { forecastLeadKey, leadLabel, type ForecastEvidenceSeries } from "@/features/charts/forecast-evidence";
import { hasInterval } from "@/features/charts/forecast-key";

const percent = (part: number, whole: number) => `${Number((part / whole * 100).toPrecision(2))} %`;
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
