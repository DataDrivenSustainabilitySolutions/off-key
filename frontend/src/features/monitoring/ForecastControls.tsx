import { forecastLeadKey, formatForecastValue, intervalStatus, latestForecast, leadLabel, type ForecastEvidenceSeries } from "@/features/charts/forecast-evidence";
import { formatChartTime } from "@/features/charts/telemetry-chart";

export function ForecastControls({ forecasts, lead, onLead, showScores, onScores, intervalLabel, timeZone }: {
  forecasts: ForecastEvidenceSeries[]; lead: string; onLead: (lead: string) => void;
  showScores: boolean; onScores: (show: boolean) => void; intervalLabel: string; timeZone: string;
}) {
  const leads = [...new Set(forecasts.map(forecast => forecast.lead))];
  const hasInterval = forecasts.some(forecast => forecastLeadKey(forecast.lead) === lead
    && forecast.data.some(point => point.value[2] !== null && point.value[3] !== null));
  return <div className="mn-forecast-controls">
    <div className="mn-forecast-toolbar">
      {leads.length > 1 ? <label>Forecast lead <select aria-label="Forecast lead" value={lead} onChange={event => onLead(event.target.value)}>
        {leads.map(value => <option key={forecastLeadKey(value)} value={forecastLeadKey(value)}>{leadLabel(value)}</option>)}
      </select></label> : <strong>{leadLabel(leads[0] ?? null)}</strong>}
      <label><input type="checkbox" checked={showScores} onChange={event => onScores(event.target.checked)} />Show detector scores</label>
    </div>
    <p className="mn-history-key">Solid: observed · Dashed: forecast{hasInterval ? <> · Shaded: {intervalLabel}.</> : ". No calibrated interval was recorded for this lead."}
      {" "}Residual = observed − forecast{hasInterval ? "; red dots fall outside the interval." : "."}</p>
    <p className="mn-history-key">Forecasts are aligned to the observations they predicted. Leads count updates, not elapsed time. Only recorded leads are available.</p>
    <details className="mn-forecast-summary"><summary>Latest forecast results{leads.length > 1 ? ` · ${leads.length} leads` : ""}</summary>
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
