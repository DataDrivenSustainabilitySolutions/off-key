import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Minus, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EChart } from "../charts/EChart";
import { formatChartTime, getLocalTimeZone } from "../charts/telemetry-chart";
import { useChartColors } from "../charts/use-chart-colors";
import { datasetChartOption, dojoChartExtent, type DojoChartData } from "./dojo-chart";

type Range = [number, number];
type Props = {
  data: DojoChartData;
  description: string;
  onRangeChange?: (range: Range | null) => void;
};

const PAGE_SIZE = 12;
const timeZone = getLocalTimeZone();
const time = (timestamp: number) => formatChartTime(timestamp, timeZone, "tooltip");
const number = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 8 });
type DataSource = { key: string; label: string; points: readonly [number, number | null][] };

function PlottedValues({ data, range }: { data: DojoChartData; range: Range }) {
  const sources = useMemo<DataSource[]>(() => [
    ...data.series.map(series => ({
      key: "series:" + series.id,
      label: series.unit ? `${series.name} (${series.unit})` : series.name,
      points: series.points,
    })),
    ...(data.alarms ?? []).map(run => ({
      key: "alarms:" + run.id,
      label: `${run.name} alarms`,
      points: run.times.map((timestamp): [number, null] => [timestamp, null]),
    })),
  ], [data]);
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState(0);
  const source = sources.find(item => item.key === selected) ?? sources[0];
  const [from, to] = range;
  const rows = useMemo(() => source?.points.filter(([timestamp]) => timestamp >= from && timestamp <= to) ?? [],
    [source, from, to]);
  if (!source) return <p className="dj-help">Select a series or run to inspect its data.</p>;
  const lastPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const offset = currentPage * PAGE_SIZE;
  return <div className="dj-data-body">
    <label className="dj-field">Data to inspect
      <select aria-label="Data to inspect" value={source.key} onChange={event => { setSelected(event.target.value); setPage(0); }}>
        {sources.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
      </select>
    </label>
    {rows.length > 0 ? <>
      <table className="dj-table">
        <caption className="ex-sr-only">{source.label} in the selected time range</caption>
        <thead><tr><th scope="col">Time</th><th scope="col">Value or event</th></tr></thead>
        <tbody>{rows.slice(offset, offset + PAGE_SIZE).map(([timestamp, value], index) =>
          <tr key={offset + index}><td><time dateTime={new Date(timestamp).toISOString()}>{time(timestamp)}</time></td>
            <td>{value === null ? "Alarm" : number.format(value)}</td></tr>)}</tbody>
      </table>
      <div className="dj-data-pages">
        <Button variant="outline" size="sm" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous values</Button>
        <span role="status">{offset + 1}–{Math.min(offset + PAGE_SIZE, rows.length)} of {rows.length.toLocaleString()}</span>
        <Button variant="outline" size="sm" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next values</Button>
      </div>
    </> : <p role="status" className="dj-help">No plotted values or events in this time range.</p>}
  </div>;
}

/** Shared zoom and value inspection for dataset and replay charts. */
export function DojoChart({ data, description, onRangeChange }: Props) {
  const { colors, resolvedTheme } = useChartColors();
  const [viewport, setViewport] = useState<Range>();
  const [showValues, setShowValues] = useState(false);
  const domain = useMemo(() => dojoChartExtent(data), [data]);
  const range = viewport && domain && viewport[0] >= domain[0] && viewport[1] <= domain[1] ? viewport : domain;
  const zoomed = !!range && !!domain && (range[0] > domain[0] || range[1] < domain[1]);
  const option = useMemo(() => datasetChartOption({ ...data, colors, timeZone, viewport: zoomed ? range : undefined }),
    [data, colors, zoomed, range]);
  const inspect = (from: number, to: number) => {
    if (to <= from) return;
    const next: Range = [from, to];
    setViewport(next);
    onRangeChange?.(next);
  };
  const move = (factor: number, offset = 0) => {
    if (!domain || !range) return;
    const width = Math.min(domain[1] - domain[0], Math.max(1, (range[1] - range[0]) * factor));
    const from = Math.max(domain[0], Math.min((range[0] + range[1] - width) / 2 + offset * width, domain[1] - width));
    inspect(from, from + width);
  };
  return <>
    {range && <div className="dj-chart-tools">
      <p className="dj-help"><strong>Time range</strong> <span>{time(range[0])} – {time(range[1])}</span></p>
      <div role="group" aria-label="Chart controls">
        <Button variant="outline" size="icon" aria-label="Zoom in" title="Zoom in" disabled={!domain || domain[0] === domain[1]}
          onClick={() => move(0.5)}><Plus /></Button>
        <Button variant="outline" size="icon" aria-label="Zoom out" title="Zoom out" disabled={!zoomed} onClick={() => move(2)}><Minus /></Button>
        <Button variant="outline" size="icon" aria-label="Earlier time window" title="Earlier time window" disabled={!domain || range[0] <= domain[0]}
          onClick={() => move(1, -0.5)}><ArrowLeft /></Button>
        <Button variant="outline" size="icon" aria-label="Later time window" title="Later time window" disabled={!domain || range[1] >= domain[1]}
          onClick={() => move(1, 0.5)}><ArrowRight /></Button>
        <Button variant="outline" size="sm" disabled={!zoomed} onClick={() => { setViewport(undefined); onRangeChange?.(null); }}><RotateCcw />Reset zoom</Button>
      </div>
    </div>}
    <EChart option={option} resolvedTheme={resolvedTheme} accessibleDescription={description} onViewportChange={inspect}
      className={data.alarms ? "dj-chart dj-chart--alarms" : "dj-chart"} />
    {range && <details className="dj-data" onToggle={event => setShowValues(event.currentTarget.open)}>
      <summary>Inspect plotted values</summary>
      {showValues && <PlottedValues data={data} range={range} />}
    </details>}
  </>;
}
