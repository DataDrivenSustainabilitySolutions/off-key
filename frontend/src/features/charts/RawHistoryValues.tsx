import { useState } from "react";
import type { HistoryPoint } from "@/types/telemetry-history";

/** Exact original timestamps stay available even when pixels cannot separate samples. */
export function RawHistoryValues({ points, unit }: { points: HistoryPoint[]; unit?: string }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(points.length / 50));
  const current = Math.min(page, pages - 1);
  const end = points.length - current * 50;
  const visible = points.slice(Math.max(0, end - 50), end).reverse();
  return <details className="ex-history-values"><summary>Values · {points.length.toLocaleString()} readings</summary>
    <table><thead><tr><th scope="col">Measured at (UTC)</th><th scope="col">Value{unit && ` (${unit})`}</th></tr></thead>
      <tbody>{visible.map(point => <tr key={point.timestamp}><td><time dateTime={point.timestamp}>{point.timestamp}</time></td>
        <td>{String(point.value)}</td></tr>)}</tbody></table>
    {pages > 1 && <div className="ex-history-tools" role="group" aria-label="Raw values pages">
      <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Newer</button>
      <span>{current + 1} / {pages}</span>
      <button type="button" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>Older</button>
    </div>}
  </details>;
}
