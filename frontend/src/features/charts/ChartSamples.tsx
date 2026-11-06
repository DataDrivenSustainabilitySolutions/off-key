import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ChartSampleSource } from "./chart-sample-data";
import { formatChartTime } from "./telemetry-chart";
import "./chart-samples.css";

type Props = {
  sources: readonly ChartSampleSource[];
  range?: readonly [number, number];
  timeZone: string;
};

const PAGE_SIZE = 12;
const label = (source: ChartSampleSource) => source.unit ? `${source.name} (${source.unit})` : source.name;

function SampleTable({ sources, range, timeZone }: Props) {
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState(0);
  const source = sources.find(item => item.id === selected) ?? sources[0];
  const [from, to] = range ?? [-Infinity, Infinity];
  const rows = useMemo(() => source?.points.filter(([timestamp]) => timestamp >= from && timestamp <= to) ?? [],
    [source, from, to]);
  if (!source) return <p className="chart-samples-empty">Select a series or run to inspect its data.</p>;
  const lastPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const offset = currentPage * PAGE_SIZE;
  return <div className="chart-samples-body">
    {sources.length > 1 && <label className="chart-samples-source">Data to inspect
      <select aria-label="Data to inspect" value={source.id} onChange={event => { setSelected(event.target.value); setPage(0); }}>
        {sources.map(item => <option key={item.id} value={item.id}>{label(item)}</option>)}
      </select>
    </label>}
    {rows.length > 0 ? <>
      <table>
        <caption className="sr-only">{label(source)} in the selected time range</caption>
        <thead><tr><th scope="col">Time</th><th scope="col">{source.unit ? `Value (${source.unit})` : "Value or event"}</th></tr></thead>
        <tbody>{rows.slice(offset, offset + PAGE_SIZE).map(([timestamp, value], index) => {
          const date = new Date(timestamp);
          const milliseconds = date.getUTCMilliseconds();
          return <tr key={offset + index}><td><time dateTime={date.toISOString()}>
            {formatChartTime(timestamp, timeZone, "tooltip")}{milliseconds > 0 && ` (${milliseconds} ms)`}
          </time></td><td>{value === null ? source.valueType === "alarm" ? "Alarm" : "—"
            : source.valueType === "boolean" ? String(Boolean(value)) : String(value)}</td></tr>;
        })}</tbody>
      </table>
      <div className="chart-samples-pages">
        <Button variant="outline" size="sm" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous values</Button>
        <span role="status">{offset + 1}–{Math.min(offset + PAGE_SIZE, rows.length)} of {rows.length.toLocaleString()}</span>
        <Button variant="outline" size="sm" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next values</Button>
      </div>
    </> : <p role="status" className="chart-samples-empty">No plotted values or events in this time range.</p>}
  </div>;
}

/** The time and value pairs behind a chart's current view. */
export function ChartSamples(props: Props) {
  const [open, setOpen] = useState(false);
  return <details className="chart-samples" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Inspect plotted values</summary>
    {open && <SampleTable {...props} />}
  </details>;
}
