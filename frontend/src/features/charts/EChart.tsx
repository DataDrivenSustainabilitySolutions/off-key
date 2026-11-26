import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactElement,
} from "react";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  AxisPointerComponent,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  GridComponent,
  LegendScrollComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { format as echartsFormat, init, use as registerEChartsModules, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { ResolvedTheme } from "@/components/theme-provider";
import {
  createEChartsTheme,
  resolveChartThemeColors,
} from "./echarts-theme";
import type { TelemetryChartOption } from "./telemetry-chart";
import { valueAxisGutter } from "./axis-labels";

registerEChartsModules([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendScrollComponent,
  AxisPointerComponent,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  AriaComponent,
  CanvasRenderer,
]);

export interface EChartProps {
  option: TelemetryChartOption;
  resolvedTheme: ResolvedTheme;
  accessibleDescription: string;
  onViewportChange?: (startMs: number, endMs: number) => void;
  /** Where the plot begins once the value labels are measured, for what is drawn beside the chart. */
  onGutter?: (left: number) => void;
  className?: string;
}

type DataZoomPayload = {
  start?: unknown;
  end?: unknown;
  startValue?: unknown;
  endValue?: unknown;
  batch?: DataZoomPayload[];
};

const finiteNumber = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === "") return undefined;
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : undefined;
};

const getAxisExtent = (chart: EChartsType): [number, number] | undefined => {
  const option = chart.getOption() as {
    xAxis?: Array<{ min?: unknown; max?: unknown }>;
  };
  const axis = option.xAxis?.[0];
  const minimum = finiteNumber(axis?.min);
  const maximum = finiteNumber(axis?.max);
  return minimum !== undefined && maximum !== undefined && maximum >= minimum
    ? [minimum, maximum]
    : undefined;
};

const getViewport = (
  chart: EChartsType,
  payload: DataZoomPayload,
): [number, number] | undefined => {
  const event = payload.batch?.[0] ?? payload;
  const startValue = finiteNumber(event.startValue);
  const endValue = finiteNumber(event.endValue);
  if (startValue !== undefined && endValue !== undefined) {
    return startValue <= endValue
      ? [startValue, endValue]
      : [endValue, startValue];
  }

  const extent = getAxisExtent(chart);
  const start = finiteNumber(event.start);
  const end = finiteNumber(event.end);
  if (!extent || start === undefined || end === undefined) return undefined;
  const duration = extent[1] - extent[0];
  const startMs = extent[0] + duration * (start / 100);
  const endMs = extent[0] + duration * (end / 100);
  return startMs <= endMs ? [startMs, endMs] : [endMs, startMs];
};

/**
 * zrender 6.1 gives a canvas it first creates while resizing the size from before the
 * resize, and afterwards finds nothing left to change: a chart whose container grows
 * before its first paint stays cut off at the old height. Resizing away and back
 * makes it size the canvas it now has.
 */
const resizeChart = (chart: EChartsType, container: HTMLElement) => {
  chart.resize({ silent: true });
  const canvas = container.querySelector("canvas");
  if (!canvas || (canvas.clientWidth === chart.getWidth() && canvas.clientHeight === chart.getHeight())) return;
  chart.resize({ width: chart.getWidth() + 1, silent: true });
  chart.resize({ width: "auto", silent: true });
};

/** The parts of ECharts' model that show which value labels an axis draws. */
interface ValueAxisModel {
  get: (path: string[]) => unknown;
  axis?: {
    getViewLabels?: () => Array<{ formattedLabel: string }>;
    getLabelModel?: () => { getFont?: () => string };
  };
}
interface ChartWithModel {
  getModel?: () => { eachComponent?: (type: string, visit: (axis: ValueAxisModel) => void) => void } | undefined;
}

/** The width of the widest value label each y axis draws now, at the font it draws in. */
const valueLabelWidths = (chart: EChartsType): number[] => {
  const widths: number[] = [];
  (chart as unknown as ChartWithModel).getModel?.()?.eachComponent?.("yAxis", axisModel => {
    if (axisModel.get(["show"]) === false || axisModel.get(["axisLabel", "show"]) === false) return;
    const font = axisModel.axis?.getLabelModel?.()?.getFont?.();
    for (const { formattedLabel } of axisModel.axis?.getViewLabels?.() ?? []) {
      widths.push(echartsFormat.getTextRect(formattedLabel, font).width);
    }
  });
  return widths;
};

const asList = <T,>(value: T | T[] | undefined): T[] => Array.isArray(value) ? value : value ? [value] : [];

/** Every pane, and the zoom slider under them, starts where the value labels end, so the panes' times line up. */
const withGutter = (option: TelemetryChartOption, left: number): TelemetryChartOption => ({
  ...option,
  grid: asList(option.grid).map(grid => ({ ...grid, left })),
  dataZoom: asList(option.dataZoom).map(zoom => zoom.type === "slider" ? { ...zoom, left } : zoom),
});

/** Only the gutter, so a zoom the reader made stays where it is. */
const gutterOnly = (option: TelemetryChartOption, left: number): TelemetryChartOption => ({
  grid: asList(option.grid).map(() => ({ left })),
  dataZoom: asList(option.dataZoom).filter(zoom => zoom.type === "slider").map(zoom => ({ id: zoom.id, left })),
});

export function EChart({
  option,
  resolvedTheme,
  accessibleDescription,
  onViewportChange,
  onGutter,
  className,
}: EChartProps): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | undefined>(undefined);
  const appliedThemeRef = useRef<ResolvedTheme | undefined>(undefined);
  const initialThemeRef = useRef(resolvedTheme);
  const viewportCallbackRef = useRef(onViewportChange);
  const gutterCallbackRef = useRef(onGutter);
  const axisIdsRef = useRef<string | undefined>(undefined);
  const optionRef = useRef(option);
  const gutterRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    viewportCallbackRef.current = onViewportChange;
    gutterCallbackRef.current = onGutter;
  }, [onViewportChange, onGutter]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const initialTheme = initialThemeRef.current;
    const colors = resolveChartThemeColors(initialTheme);
    const chart = init(container, createEChartsTheme(colors), {
      renderer: "canvas",
    });
    chartRef.current = chart;
    appliedThemeRef.current = initialTheme;

    const handleDataZoom = (payload: unknown) => {
      const viewport = getViewport(chart, payload as DataZoomPayload);
      if (viewport) viewportCallbackRef.current?.(...viewport);
    };
    chart.on("datazoom", handleDataZoom);
    // Value labels are only known once ECharts has chosen the ticks. When they no longer
    // fit the gutter, or leave it needlessly wide, the panes move to fit them.
    const fitGutter = () => {
      const widths = valueLabelWidths(chart);
      if (!widths.length) return;
      const gutter = valueAxisGutter(widths);
      if (gutter === gutterRef.current) return;
      gutterRef.current = gutter;
      gutterCallbackRef.current?.(gutter);
      chart.setOption(gutterOnly(optionRef.current, gutter), { lazyUpdate: true });
    };
    chart.on("finished", fitGutter);

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(() => resizeChart(chart, container));
    resizeObserver?.observe(container);

    return () => {
      resizeObserver?.disconnect();
      chart.off("datazoom", handleDataZoom);
      chart.off("finished", fitGutter);
      chart.dispose();
      chartRef.current = undefined;
      appliedThemeRef.current = undefined;
      axisIdsRef.current = undefined;
      gutterRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || appliedThemeRef.current === resolvedTheme) return;
    chart.setTheme(
      createEChartsTheme(resolveChartThemeColors(resolvedTheme)),
      { silent: true },
    );
    appliedThemeRef.current = resolvedTheme;
  }, [resolvedTheme]);

  useEffect(() => {
    const axisIds = JSON.stringify([option.xAxis, option.yAxis].map(axes =>
      (Array.isArray(axes) ? axes : axes ? [axes] : []).map(axis => axis.id)));
    // ECharts retains component indices when merging stable axis IDs. Replacing
    // the axis set must rebuild those indices before series refer to them.
    const axesChanged = axisIdsRef.current !== undefined && axisIdsRef.current !== axisIds;
    optionRef.current = option;
    const gutter = gutterRef.current;
    chartRef.current?.setOption(gutter === undefined ? option : withGutter(option, gutter), {
      lazyUpdate: true,
      ...(axesChanged ? { notMerge: true } : {}),
      replaceMerge: ["series", "grid", "xAxis", "yAxis", "dataZoom"],
    });
    axisIdsRef.current = axisIds;
  }, [option]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={accessibleDescription}
      className={className ?? "h-[420px] w-full min-w-0 touch-none"}
      data-testid="telemetry-echart"
    />
  );
}
