import { forecastLeadKey, formatForecastValue, intervalStatus, latestForecast, leadLabel, type ForecastEvidenceSeries } from "@/features/charts/forecast-evidence";
import { formatChartTime } from "@/features/charts/telemetry-chart";

const percent = (part: number, whole: number) => `${Number((part / whole * 100).toPrecision(2))} %`;

/** A swatch for each mark the chart draws; colours follow each reading, so they stay neutral here. */
function Swatch({ kind, color }: { kind: "observed" | "forecast" | "interval" | "outside"; color?: string }) {
  return <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
    {kind === "interval" && <rect x="1" y="2" width="20" height="8" rx="2" fill="currentColor" opacity=".2" />}
    {(kind === "observed" || kind === "forecast") && <path d="M1 6h20" stroke="currentColor" strokeWidth="2"
      strokeDasharray={kind === "forecast" ? "4 3" : undefined} />}
    {kind === "outside" && <circle cx="11" cy="6" r="4" fill="none" stroke={color ?? "currentColor"} strokeWidth="2" />}
  </svg>;
}

export function ForecastControls({ forecasts, lead, onLead, showScores, onScores, intervalLabel, timeZone,
  coverage, outsideColor, showResiduals, onResiduals }: {
  forecasts: ForecastEvidenceSeries[]; lead: string; onLead: (lead: string) => void;
  showScores: boolean; onScores: (show: boolean) => void; intervalLabel: string; timeZone: string;
  coverage: { checked: number; outside: number }; outsideColor?: string;
  showResiduals: boolean; onResiduals: (show: boolean) => void;
}) {
  const leads = [...new Set(forecasts.map(forecast => forecast.lead))];
  const shown = forecasts.filter(forecast => forecastLeadKey(forecast.lead) === lead);
  const hasInterval = shown.some(forecast => forecast.data.some(point => point.value[2] !== null && point.value[3] !== null));
  return <div className="mn-forecast-controls">
    <div className="mn-forecast-toolbar">
      {leads.length > 1 ? <select aria-label="Forecast lead" value={lead} onChange={event => onLead(event.target.value)}>
        {leads.map(value => <option key={forecastLeadKey(value)} value={forecastLeadKey(value)}>{leadLabel(value)}</option>)}
      </select> : <strong>{leadLabel(leads[0] ?? null)}</strong>}
      <ul className="mn-forecast-legend" aria-label="Chart key">
        <li><Swatch kind="observed" />Observed</li>
        <li><Swatch kind="forecast" />Forecast</li>
        {hasInterval && <li><Swatch kind="interval" />{intervalLabel}</li>}
        {hasInterval && <li role="status" title="Outside the interval is not an anomaly by itself.">
          <Swatch kind="outside" color={outsideColor} />Outside{coverage.checked > 0
            && <strong>{coverage.outside} of {coverage.checked} · {percent(coverage.outside, coverage.checked)}</strong>}</li>}
      </ul>
      <label><input type="checkbox" checked={showResiduals} onChange={event => onResiduals(event.target.checked)} />Residuals</label>
      <label><input type="checkbox" checked={showScores} onChange={event => onScores(event.target.checked)} />Scores</label>
    </div>
    <details className="mn-forecast-summary"><summary>Latest results</summary>
      <div className="mn-forecast-table"><table><caption>Latest evaluated forecast for each recorded lead</caption>
        <thead><tr><th scope="col">Forecast</th><th scope="col">Evaluated at</th><th scope="col">Residual</th><th scope="col">{intervalLabel}</th><th scope="col">Result</th></tr></thead>
        <tbody>{forecasts.map(forecast => {
          const point = latestForecast(forecast);
          return <tr key={forecast.id} aria-current={forecastLeadKey(forecast.lead) === lead ? "true" : undefined}>
            <th scope="row"><button type="button" onClick={() => onLead(forecastLeadKey(forecast.lead))}>{forecast.name}</button></th>
            <td>{point ? formatChartTime(point.time, timeZone) : "No current forecast"}</td>
            <td>{point?.observed == null ? "Unavailable" : formatForecastValue(point.observed - point.expected)}</td>
            <td>{point?.lower == null || point.upper === null ? "Unavailable" : `${formatForecastValue(point.lower)} to ${formatForecastValue(point.upper)}`}</td>
            <td>{point ? intervalStatus(point) : "Unavailable"}</td>
          </tr>;
        })}</tbody>
      </table></div>
    </details>
  </div>;
}
