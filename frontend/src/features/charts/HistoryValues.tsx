import { useState } from "react";
import type { TelemetryHistory } from "@/types/telemetry-history";
import { intervalLabel } from "./history-presentation";

const PAGE = 50;
const MEAN = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3, useGrouping: false });

/**
 * The values behind the chart, newest first. Original samples keep their exact timestamps
 * even when pixels cannot separate them; averaged history lists each interval's mean and range.
 */
export function HistoryValues({ history, unit }: { history: TelemetryHistory; unit?: string }) {
  const [page, setPage] = useState(0);
  const { points } = history;
  const means = history.representation === "mean";
  const pages = Math.max(1, Math.ceil(points.length / PAGE));
  const current = Math.min(page, pages - 1);
  const end = points.length - current * PAGE;
  const visible = points.slice(Math.max(0, end - PAGE), end).reverse();
  const readings = means ? history.sample_count : points.length;
  const thinned = !means && !!history.column_ms;
  const suffix = unit ? ` (${unit})` : "";
  return <details className="ex-history-values"><summary>Values · {readings.toLocaleString()} {readings === 1 ? "reading" : "readings"}
    {means && ` · ${intervalLabel(history.interval_ms)} means`}
    {thinned && ` of ${history.sample_count.toLocaleString()} · first, last, lowest and highest per ${intervalLabel(history.column_ms!)}; zoom in for every reading`}</summary>
    <table><thead><tr>{means ? <>
      <th scope="col">Interval from (UTC)</th><th scope="col">Mean{suffix}</th><th scope="col">Min</th><th scope="col">Max</th><th scope="col">Readings</th>
    </> : <><th scope="col">Measured at (UTC)</th><th scope="col">Value{suffix}</th></>}</tr></thead>
      <tbody>{visible.map(point => <tr key={point.timestamp}>
        <td><time dateTime={point.start ?? point.timestamp}>{point.start ?? point.timestamp}</time></td>
        {/* A mean is calculated, so its trailing digits say nothing; a sample is shown as recorded. */}
        <td>{means && typeof point.value === "number" ? MEAN.format(point.value) : String(point.value)}</td>
        {means && <><td>{point.minimum ?? "—"}</td><td>{point.maximum ?? "—"}</td><td>{point.count?.toLocaleString() ?? "—"}</td></>}
      </tr>)}</tbody></table>
    {pages > 1 && <div className="ex-history-tools" role="group" aria-label="Values pages">
      <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Newer</button>
      <span>{current + 1} / {pages}</span>
      <button type="button" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>Older</button>
    </div>}
  </details>;
}
