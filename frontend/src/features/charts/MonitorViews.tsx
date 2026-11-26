import { useSyncExternalStore } from "react";
import "./anomaly-strip.css";

export const RAW_VIEW = "raw";
export type MonitorView = { id: string; name: string; color: string };

const NARROW = "(max-width: 640px)";
const watchNarrow = (notify: () => void) => {
  const query = matchMedia(NARROW);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
};

/** Chooses what a reading's chart shows: its raw data, or one of the monitors that watch it. */
export function MonitorViews({ monitors, value, onChange, aimed }: {
  monitors: readonly MonitorView[]; value: string; onChange: (view: string) => void;
  /** The monitor the pointer rests on in the anomaly strip. */
  aimed?: string;
}) {
  const narrow = useSyncExternalStore(watchNarrow, () => matchMedia(NARROW).matches, () => false);
  if (!monitors.length) return null;
  if (narrow || monitors.length > 3) return <select className="an-views-select" aria-label="Chart view" value={value}
    onChange={event => onChange(event.target.value)}>
    <option value={RAW_VIEW}>Raw data</option>
    {monitors.map(monitor => <option key={monitor.id} value={monitor.id}>{monitor.name}</option>)}
  </select>;
  return <div className="an-views" role="group" aria-label="Chart view">
    <button type="button" aria-pressed={value === RAW_VIEW} onClick={() => onChange(RAW_VIEW)}>Raw data</button>
    {monitors.map(monitor => <button key={monitor.id} type="button" aria-pressed={value === monitor.id}
      className={aimed === monitor.id ? "is-aimed" : undefined} onClick={() => onChange(monitor.id)}>
      <i style={{ background: monitor.color }} />{monitor.name}</button>)}
  </div>;
}
