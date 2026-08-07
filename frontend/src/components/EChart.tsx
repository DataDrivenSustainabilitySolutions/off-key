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
import { init, use as registerEChartsModules, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { ResolvedTheme } from "@/components/theme-provider";
import {
  createEChartsTheme,
  resolveChartThemeColors,
} from "@/lib/echarts-theme";
import type { TelemetryChartOption } from "@/lib/telemetry-chart";

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

export function EChart({
  option,
  resolvedTheme,
  accessibleDescription,
  onViewportChange,
  className,
}: EChartProps): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | undefined>(undefined);
  const appliedThemeRef = useRef<ResolvedTheme | undefined>(undefined);
  const initialThemeRef = useRef(resolvedTheme);
  const viewportCallbackRef = useRef(onViewportChange);

  useEffect(() => {
    viewportCallbackRef.current = onViewportChange;
  }, [onViewportChange]);

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

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(() => chart.resize({ silent: true }));
    resizeObserver?.observe(container);

    return () => {
      resizeObserver?.disconnect();
      chart.off("datazoom", handleDataZoom);
      chart.dispose();
      chartRef.current = undefined;
      appliedThemeRef.current = undefined;
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
    chartRef.current?.setOption(option, {
      lazyUpdate: true,
      replaceMerge: ["series", "grid", "xAxis", "yAxis", "dataZoom"],
    });
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
