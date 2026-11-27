import "./chart-key.css";

type SwatchKind = "observed" | "forecast" | "interval" | "outside" | "threshold" | "above" | "alarm" | "alarm-bar" | "label" | "muted";

/** A swatch for each mark the chart draws. Reading colours vary, so those stay neutral; the
 * colours that carry a meaning (outside the interval, alarm) are the chart's own. */
function Swatch({ kind, color }: { kind: SwatchKind; color?: string }) {
  return <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true" style={color ? { color } : undefined}>
    {kind === "interval" && <rect x="1" y="2" width="20" height="8" rx="2" fill="currentColor" opacity=".2" />}
    {kind === "alarm" && <rect x="4" y="0" width="16" height="12" fill="currentColor" opacity=".16" />}
    {kind === "alarm" && <path d="M4.5 0v12" stroke="currentColor" strokeWidth="1" opacity=".7" />}
    {kind === "alarm-bar" && <rect x="1" y="3" width="20" height="6" fill="currentColor" />}
    {kind === "label" && <rect x="1" y="0" width="20" height="12" fill="currentColor" opacity=".16" />}
    {kind === "above" && <path d="M1 9 L7 9 L11 3 L15 9 L21 9 Z" fill="currentColor" opacity=".14" />}
    {kind === "above" && <path d="M1 9 L7 9 L11 3 L15 9 L21 9" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />}
    {kind === "threshold" && <path d="M1 6h20" stroke="currentColor" strokeWidth="1" strokeDasharray="4 3" />}
    {kind === "muted" && <circle cx="11" cy="6" r="3" fill="none" stroke="currentColor" strokeWidth="1.2" />}
    {kind === "outside" && <path d="M1 8 Q11 0 21 8 Z" fill="currentColor" opacity=".4" />}
    {(kind === "observed" || kind === "forecast") && <path d="M1 6h20" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeDasharray={kind === "forecast" ? "4 3" : undefined} />}
  </svg>;
}

export type KeyEntry = { kind: SwatchKind; label: string; color?: string };

/** The marks on the chart, each named once, in place of a sentence that explains colours. */
export function ChartKey({ entries }: { entries: readonly KeyEntry[] }) {
  if (!entries.length) return null;
  return <ul className="chart-key" aria-label="Chart key">
    {entries.map(entry => <li key={entry.kind}><Swatch kind={entry.kind} color={entry.color} />{entry.label}</li>)}
  </ul>;
}
