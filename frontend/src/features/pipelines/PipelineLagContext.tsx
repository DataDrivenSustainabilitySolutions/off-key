import { useContext, useEffect, useId, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import type { Autocorrelation } from "@/types/dojo.generated";
import { cycleLag, duration, LagReadingsContext, type LagProfile, redundantPairs, suggestedLags } from "./lagContext";

type Unit = { short: string; seconds?: number };
type Loaded = { id: string; profile?: LagProfile; error?: string };

const SHOWN_LAGS = 48;

/** Correlation by lag as thin bars around zero, with the band noise stays within. */
function Correlogram({ label, values, bound, step }: { label: string; values: number[]; bound: number; step: number }) {
  const shown = values.slice(0, SHOWN_LAGS);
  const width = 240, height = 64, middle = height / 2, gap = width / Math.max(shown.length, 1);
  const y = (value: number) => middle - value * (middle - 2);
  return <figure className="pl-correlogram">
    <figcaption>{label}</figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} over ${shown.length} lags`}>
      <rect className="pl-correlogram-band" x={0} width={width} y={y(bound)} height={y(-bound) - y(bound)} />
      <line className="pl-correlogram-axis" x1={0} x2={width} y1={middle} y2={middle} />
      {shown.map((value, index) => {
        const top = Math.min(y(value), middle), size = Math.max(Math.abs(y(value) - middle), 1);
        return <g key={index}>
          <rect className="pl-correlogram-bar" x={index * gap + gap * 0.2} width={Math.max(gap * 0.6, 1)} y={top} height={size} rx={1} />
          <rect className="pl-correlogram-hit" x={index * gap} width={gap} y={0} height={height}>
            <title>{`${duration((index + 1) * step)} back: ${value.toFixed(2)}`}</title>
          </rect>
        </g>;
      })}
    </svg>
    <small>1 to {shown.length} steps of {duration(step)}; the band is noise (±{bound.toFixed(2)}).</small>
  </figure>;
}

function seasonsOf(items: Autocorrelation[]) {
  const seasons = items.flatMap((item) => item.seasons ?? []);
  return seasons.filter((season, index) =>
    seasons.findIndex((other) => Math.abs(other.seconds - season.seconds) <= 0.05 * season.seconds) === index);
}

/** How the readings this design watches relate to their own past, and which lags that suggests. */
export function PipelineLagContext({ lags, unit, readOnly, onLags }: {
  lags: number[]; unit: Unit; readOnly?: boolean; onLags: (lags: number[]) => void;
}) {
  const id = useId();
  const readings = useContext(LagReadingsContext);
  const [chosen, setChosen] = useState<string>();
  const reading = readings.find((item) => item.id === chosen) ?? readings[0];
  const [loaded, setLoaded] = useState<Loaded>();
  const readingId = reading?.id;
  useEffect(() => {
    if (!readingId) return;
    const controller = new AbortController();
    apiUtils.get<LagProfile>(API_CONFIG.ENDPOINTS.READINGS.PROFILE(readingId), { signal: controller.signal })
      .then((profile) => setLoaded({ id: readingId, profile }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoaded({ id: readingId, error: error instanceof Error ? error.message : "Could not load" });
      });
    return () => controller.abort();
  }, [readingId]);
  if (!reading) return <p className="pl-help">Choose readings for this design to see how they relate to their past and which lags fit them.</p>;
  const current = loaded?.id === reading.id ? loaded : undefined;
  const item = current?.profile?.autocorrelation[0];
  const suggested = item ? suggestedLags(item, unit) : [];
  const seasons = current?.profile ? seasonsOf(current.profile.autocorrelation) : [];
  const pairs = item ? redundantPairs(lags, item, unit) : [];
  const wanders = current?.profile?.autocorrelation.some((entry) => entry.persistent);
  const name = (lag: number) => unit.seconds ? `${lag} ${unit.short}` : `${lag}`;
  return <section className="pl-lag-context" aria-labelledby={`${id}-title`}>
    <h4 id={`${id}-title`}>How {readings.length > 1 ? "a reading" : reading.label} relates to its past</h4>
    {readings.length > 1 && <select aria-label="Reading" value={reading.id} onChange={(event) => setChosen(event.target.value)}>
      {readings.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
    </select>}
    {!current && <p className="pl-help" role="status">Reading the last 14 days…</p>}
    {current?.error && <p className="pl-help" role="alert">The profile is unavailable: {current.error}</p>}
    {current?.profile && !item && <p className="pl-help">Too few values that vary to say how this reading relates to its past.</p>}
    {item && <>
      <Correlogram label="Autocorrelation" values={item.acf} bound={item.bound} step={item.step_seconds} />
      <Correlogram label="Partial autocorrelation" values={item.pacf} bound={item.bound} step={item.step_seconds} />
      {wanders && <p className="pl-help">The values wander: they stay correlated far back. Lags of a wandering level mostly
        repeat it, so take the time out first with a Change step or a forecaster, then lag what is left.</p>}
      {!unit.seconds && !item.regular && <p className="pl-help">This reading arrives unevenly, so a lag in observations is not
        a fixed time back. Count in time instead.</p>}
      {suggested.length > 0 ? <div className="pl-lag-suggestion">
        <p className="pl-help">Partial autocorrelation points to {suggested.map(name).join(", ")}: each adds something the shorter lags do not.</p>
        <button type="button" disabled={readOnly || suggested.join() === lags.join()} onClick={() => onLags(suggested)}>Use these</button>
      </div> : <p className="pl-help">No lag stands out from noise in the partial autocorrelation.</p>}
      {pairs.map((pair) => <p key={`${pair.one}-${pair.other}`} className="pl-help">
        {name(pair.one)} and {name(pair.other)} move together (autocorrelation {pair.correlation.toFixed(2)}), so one of them
        carries most of what both say.</p>)}
    </>}
    {seasons.map((season) => {
      const lag = cycleLag(season.seconds, season.observations, unit);
      return <div key={season.seconds} className="pl-lag-suggestion">
        <p className="pl-help">A cycle of {duration(season.seconds)} (autocorrelation {season.strength.toFixed(2)}): a lag of one cycle
          compares each value with the same moment before.</p>
        {lag && !lags.includes(lag) && <button type="button" disabled={readOnly}
          onClick={() => onLags([...lags, lag].sort((one, other) => one - other))}>Add {name(lag)}</button>}
      </div>;
    })}
  </section>;
}
