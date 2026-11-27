import { useState } from "react";
import type { TelemetryHistory } from "@/types/telemetry-history";
import { intervalLabel } from "./history-presentation";

const PAGE = 50;
const TIME = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const PRECISE = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  fractionalSecondDigits: 3, hourCycle: "h23" });
/** Readable, yet exact: milliseconds appear whenever a reading carries them. */
const formatTime = (value: string) => {
  const date = new Date(value);
  return (date.getTime() % 1000 ? PRECISE : TIME).format(date);
};
const MEAN = new Intl.NumberFormat("en", { maximumFractionDigits: 3, useGrouping: false });

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
  const count = new Intl.NumberFormat("en");
  return <section className="ex-history-values" aria-label="Values"><p>
    {means ? `${intervalLabel(history.interval_ms)} means of ${count.format(readings)} readings`
      : thinned ? `${count.format(readings)} of ${count.format(history.sample_count)} readings: first, last, lowest and highest per ${intervalLabel(history.column_ms!)}. Zoom in for every reading.`
        : `${count.format(readings)} ${readings === 1 ? "reading" : "readings"}`}, newest first</p>
    <table><thead><tr>{means ? <>
      <th scope="col">Interval from</th><th scope="col">Mean{suffix}</th><th scope="col">Min</th><th scope="col">Max</th><th scope="col">Readings</th>
    </> : <><th scope="col">Measured at</th><th scope="col">Value{suffix}</th></>}</tr></thead>
      <tbody>{visible.map(point => <tr key={point.timestamp}>
        <td><time dateTime={point.start ?? point.timestamp} title={point.start ?? point.timestamp}>{formatTime(point.start ?? point.timestamp)}</time></td>
        {/* A mean is calculated, so its trailing digits say nothing; a sample is shown as recorded. */}
        <td>{means && typeof point.value === "number" ? MEAN.format(point.value) : String(point.value)}</td>
        {means && <><td>{point.minimum ?? "—"}</td><td>{point.maximum ?? "—"}</td><td>{point.count === undefined ? "—" : count.format(point.count)}</td></>}
      </tr>)}</tbody></table>
    {pages > 1 && <div className="ex-history-tools" role="group" aria-label="Values pages">
      <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Newer</button>
      <span>{current + 1} / {pages}</span>
      <button type="button" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>Older</button>
    </div>}
  </section>;
}
