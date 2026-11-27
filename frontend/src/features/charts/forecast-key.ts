import type { KeyEntry } from "./ChartKey";
import { isOutside, type ForecastEvidenceSeries } from "./forecast-evidence";

export const hasInterval = (forecasts: readonly ForecastEvidenceSeries[]) =>
  forecasts.some(forecast => forecast.data.some(point => point.value[2] !== null && point.value[3] !== null));

/** What a forecast chart draws: the observed line, the forecast, its interval and where the line left it. */
export const forecastKeyEntries = (forecasts: readonly ForecastEvidenceSeries[], intervalLabel: string, outsideColor?: string,
  observedColor?: string): KeyEntry[] => [
  { kind: "observed", label: "Observed", color: observedColor },
  { kind: "forecast", label: "Forecast" },
  ...(hasInterval(forecasts) ? [{ kind: "interval" as const, label: intervalLabel }] : []),
  // Named only when the chart draws it.
  ...(forecasts.some(forecast => forecast.data.some(({ forecastObservation: point }) => point && !point.alarm && isOutside(point)))
    ? [{ kind: "outside" as const, label: "Outside interval", color: outsideColor }] : []),
];
