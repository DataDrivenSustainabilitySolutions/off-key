import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Minus, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EChart } from "../charts/EChart";
import { ChartSamples } from "../charts/ChartSamples";
import type { ChartSampleSource } from "../charts/chart-sample-data";
import { formatChartTime, getLocalTimeZone } from "../charts/telemetry-chart";
import { useChartColors } from "../charts/use-chart-colors";
import { chartScaleKeys, datasetChartOption, dojoChartExtent, type DojoChartData } from "./dojo-chart";

type Range = [number, number];
type Props = {
  data: DojoChartData;
  description: string;
  onRangeChange?: (range: Range | null) => void;
};

const timeZone = getLocalTimeZone();
const time = (timestamp: number) => formatChartTime(timestamp, timeZone, "tooltip");

/** Shared zoom and value inspection for dataset and replay charts. */
export function DojoChart({ data, description, onRangeChange }: Props) {
  const { colors, resolvedTheme } = useChartColors();
  const [viewport, setViewport] = useState<Range>();
  const [selectedSeries, setSelectedSeries] = useState("");
  const individualScales = chartScaleKeys(data.series).length > 2;
  const focused = data.series.find(series => series.id === selectedSeries) ?? (individualScales ? data.series[0] : undefined);
  const plotted = useMemo(() => focused ? { ...data, series: [focused] } : data, [data, focused]);
  const sources = useMemo<ChartSampleSource[]>(() => [
    ...plotted.series.map(series => ({ ...series, id: "series:" + series.id })),
    ...(plotted.alarms ?? []).map(run => ({
      id: "alarms:" + run.id, name: `${run.name} alarms`, valueType: "alarm" as const,
      points: run.times.map((timestamp): [number, null] => [timestamp, null]),
    })),
  ], [plotted]);
  const domain = useMemo(() => dojoChartExtent(plotted), [plotted]);
  const range = viewport && domain && viewport[0] >= domain[0] && viewport[1] <= domain[1] ? viewport : domain;
  const zoomed = !!range && !!domain && (range[0] > domain[0] || range[1] < domain[1]);
  const option = useMemo(() => datasetChartOption({ ...plotted, colors, timeZone, viewport: zoomed ? range : undefined }),
    [plotted, colors, zoomed, range]);
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
  const reset = () => { setViewport(undefined); onRangeChange?.(null); };
  return <>
    {data.series.length > 1 && <div className="dj-plot-selection">
      <label className="dj-field">Plot
        <select aria-label="Plot" value={focused?.id ?? ""} onChange={event => { setSelectedSeries(event.target.value); reset(); }}>
          {!individualScales && <option value="">All selected series</option>}
          {data.series.map(series => <option key={series.id} value={series.id}>{series.name}{series.unit ? ` (${series.unit})` : ""}</option>)}
        </select>
      </label>
      {individualScales && <p className="dj-help">These series use different scales. Choose one to see it on its own scale.</p>}
    </div>}
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
        <Button variant="outline" size="sm" disabled={!zoomed} onClick={reset}><RotateCcw />Reset zoom</Button>
      </div>
    </div>}
    <EChart option={option} resolvedTheme={resolvedTheme} accessibleDescription={focused ? `${description}. Showing ${focused.name}.` : description} onViewportChange={inspect}
      className={data.alarms ? "dj-chart dj-chart--alarms" : "dj-chart"} />
    {range && <ChartSamples sources={sources} range={range} timeZone={timeZone} />}
  </>;
}
