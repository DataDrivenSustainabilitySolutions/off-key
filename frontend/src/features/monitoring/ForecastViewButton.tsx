import { FORECAST_VIEW_LABELS, nextForecastView, type ForecastView } from "@/features/charts/forecast-future";

export function ForecastViewButton({ view, onChange }: { view: ForecastView; onChange: (view: ForecastView) => void }) {
  const next = nextForecastView(view);
  const label = `Forecast view: ${FORECAST_VIEW_LABELS[view]}. Switch to ${FORECAST_VIEW_LABELS[next]}`;
  return <button type="button" aria-label={label} title={label} data-forecast-view={view}
    onClick={() => onChange(next)}>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 3v18h18" opacity=".45" />
      <path d={view === "data" ? "m5 15 3-4 3 2 3-6 3 2 4-3" : "m5 15 3-4 3 2 3-6"} />
      {view !== "data" && <path d={view === "overlay" ? "m5 13 3-1 3-1 3-2 3-3 4 2" : "m14 7 3-1 4 2"}
        strokeDasharray="2 2" opacity=".7" />}
    </svg>
    <span className="sr-only" aria-live="polite">{FORECAST_VIEW_LABELS[view]}</span>
  </button>;
}
