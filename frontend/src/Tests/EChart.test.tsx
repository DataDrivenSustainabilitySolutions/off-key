import { StrictMode } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TelemetryChartOption } from "@/features/charts/telemetry-chart";

const echartsMock = vi.hoisted(() => {
  const instances: Array<{
    setOption: ReturnType<typeof vi.fn>;
    dispatchAction: ReturnType<typeof vi.fn>;
    setTheme: ReturnType<typeof vi.fn>;
    resize: ReturnType<typeof vi.fn>;
    getWidth: ReturnType<typeof vi.fn>;
    getHeight: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    off: ReturnType<typeof vi.fn>;
    getOption: ReturnType<typeof vi.fn>;
    getModel: ReturnType<typeof vi.fn>;
    handlers: Map<string, (payload: unknown) => void>;
  }> = [];
  const init = vi.fn(() => {
    const handlers = new Map<string, (payload: unknown) => void>();
    const instance = {
      setOption: vi.fn(),
      dispatchAction: vi.fn(),
      setTheme: vi.fn(),
      resize: vi.fn(),
      getWidth: vi.fn(() => 800),
      getHeight: vi.fn(() => 356),
      dispose: vi.fn(),
      on: vi.fn((event: string, handler: (payload: unknown) => void) => {
        handlers.set(event, handler);
      }),
      off: vi.fn((event: string) => handlers.delete(event)),
      getOption: vi.fn(() => ({
        xAxis: [{ min: 1_000, max: 2_000 }],
        legend: [{ selected: { Voltage: false } }],
      })),
      getModel: vi.fn(() => undefined),
      handlers,
    };
    instances.push(instance);
    return instance;
  });
  return { init, instances, register: vi.fn() };
});

vi.mock("echarts/core", () => ({
  init: echartsMock.init,
  use: echartsMock.register,
  format: { getTextRect: (text: string) => ({ width: text.length * 7 }) },
}));
vi.mock("echarts/charts", () => ({ LineChart: {}, ScatterChart: {} }));
vi.mock("echarts/components", () => ({
  AriaComponent: {},
  AxisPointerComponent: {},
  BrushComponent: {},
  DataZoomInsideComponent: {},
  DataZoomSliderComponent: {},
  GridComponent: {},
  LegendScrollComponent: {},
  MarkAreaComponent: {},
  MarkLineComponent: {},
  MarkPointComponent: {},
  ToolboxComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

import { EChart } from "@/features/charts/EChart";

const option = (id: string): TelemetryChartOption =>
  ({ series: [{ id, type: "line", data: [] }] }) as TelemetryChartOption;

let resizeCallbacks: ResizeObserverCallback[] = [];

class MockResizeObserver implements ResizeObserver {
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();

  constructor(callback: ResizeObserverCallback) {
    resizeCallbacks.push(callback);
  }
}

beforeEach(() => {
  echartsMock.init.mockClear();
  echartsMock.instances.length = 0;
  resizeCallbacks = [];
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
});


describe("EChart lifecycle", () => {
  it("initializes once, reuses the instance, and applies stable lazy updates", async () => {
    const { rerender, unmount } = render(
      <EChart
        option={option("telemetry")}
        resolvedTheme="light"
        accessibleDescription="Voltage telemetry"
      />,
    );

    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(1));
    const instance = echartsMock.instances[0];
    expect(instance).toBeDefined();
    expect(echartsMock.init).toHaveBeenCalledWith(
      expect.any(HTMLDivElement),
      expect.any(Object),
      { renderer: "canvas" },
    );
    expect(instance?.setOption).toHaveBeenLastCalledWith(expect.any(Object), {
      lazyUpdate: true,
      replaceMerge: ["series", "grid", "xAxis", "yAxis", "dataZoom"],
    });

    rerender(
      <EChart
        option={option("telemetry")}
        resolvedTheme="light"
        accessibleDescription="Updated voltage telemetry"
      />,
    );

    await waitFor(() => expect(instance?.setOption).toHaveBeenCalledTimes(2));
    expect(echartsMock.init).toHaveBeenCalledTimes(1);
    expect(instance?.dispose).not.toHaveBeenCalled();

    unmount();
    expect(instance?.off).toHaveBeenCalledWith("datazoom", expect.any(Function));
    expect(instance?.dispose).toHaveBeenCalledOnce();
  });

  it("resizes through ResizeObserver and changes theme without recreation", async () => {
    const stableOption = option("telemetry");
    const { rerender } = render(
      <EChart
        option={stableOption}
        resolvedTheme="light"
        accessibleDescription="Voltage telemetry"
      />,
    );
    const instance = echartsMock.instances[0];

    act(() => resizeCallbacks[0]?.([], {} as ResizeObserver));
    expect(instance?.resize).toHaveBeenCalledWith({ silent: true });

    rerender(
      <EChart
        option={stableOption}
        resolvedTheme="dark"
        accessibleDescription="Voltage telemetry"
      />,
    );

    await waitFor(() => expect(instance?.setTheme).toHaveBeenCalledOnce());
    expect(instance?.setTheme).toHaveBeenCalledWith(expect.any(Object), {
      silent: true,
    });
    expect(echartsMock.init).toHaveBeenCalledTimes(1);
  });

  it("picks a time range by dragging while range selection is on", () => {
    const picked = vi.fn();
    const { rerender } = render(<EChart option={option("telemetry")} resolvedTheme="light" accessibleDescription="Values"
      onRangeSelect={picked} />);
    const instance = echartsMock.instances[0]!;
    expect(instance.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({ type: "takeGlobalCursor",
      brushOption: { brushType: false } }));
    rerender(<EChart option={option("telemetry")} resolvedTheme="light" accessibleDescription="Values" rangeSelect
      onRangeSelect={picked} />);
    expect(instance.dispatchAction).toHaveBeenLastCalledWith({ type: "takeGlobalCursor", key: "brush",
      brushOption: { brushType: "lineX", brushMode: "single" } });
    // Dragged right to left, the range still runs forward, and the drawn band goes.
    act(() => instance.handlers.get("brushEnd")?.({ areas: [{ coordRange: [1_800, 1_200] }] }));
    expect(picked).toHaveBeenCalledWith(1_200, 1_800);
    expect(instance.dispatchAction).toHaveBeenLastCalledWith({ type: "brush", areas: [] });
    // A click without a drag picks nothing.
    act(() => instance.handlers.get("brushEnd")?.({ areas: [{ coordRange: [1_500, 1_500] }] }));
    expect(picked).toHaveBeenCalledTimes(1);
  });

  it("resizes again when the canvas kept the size from before the resize", () => {
    const { getByTestId } = render(<EChart option={option("telemetry")} resolvedTheme="light" accessibleDescription="Voltage telemetry" />);
    const instance = echartsMock.instances[0]!;
    // The canvas zrender creates while a chart grows before its first paint: still the old height.
    const canvas = document.createElement("canvas");
    Object.defineProperties(canvas, { clientWidth: { value: 800 }, clientHeight: { value: 208, writable: true } });
    getByTestId("telemetry-echart").append(canvas);

    act(() => resizeCallbacks[0]?.([], {} as ResizeObserver));
    expect(instance.resize.mock.calls).toEqual([[{ silent: true }], [{ width: 801, silent: true }], [{ width: "auto", silent: true }]]);

    instance.resize.mockClear();
    (canvas as { clientHeight: number }).clientHeight = 356;
    act(() => resizeCallbacks[0]?.([], {} as ResizeObserver));
    expect(instance.resize.mock.calls).toEqual([[{ silent: true }]]);
  });

  it("rebuilds axis indices when readings change while retaining the chart and explicit viewport", () => {
    const build = (ids: string[]): TelemetryChartOption => ({
      xAxis: ids.map(id => ({ id: `${id}-time`, type: "time" })),
      yAxis: ids.map(id => ({ id: `${id}-values`, type: "value" })),
      dataZoom: [{ type: "inside", startValue: 1200, endValue: 1800 }],
      series: ids.map((id, index) => ({ id, type: "line", xAxisIndex: index, yAxisIndex: index, data: [] })),
    });
    const { rerender } = render(<EChart option={build(["a", "b", "c", "score"])} resolvedTheme="light" accessibleDescription="Joint chart" />);
    const instance = echartsMock.instances[0]!;
    const reduced = build(["a", "c", "score"]);
    rerender(<EChart option={reduced} resolvedTheme="light" accessibleDescription="Joint chart" />);
    expect(instance.setOption).toHaveBeenLastCalledWith(reduced, expect.objectContaining({ notMerge: true }));
    expect(reduced.dataZoom).toMatchObject([{ startValue: 1200, endValue: 1800 }]);
    rerender(<EChart option={build(["a", "c", "score"])} resolvedTheme="light" accessibleDescription="Updated samples" />);
    expect(instance.setOption.mock.lastCall![1]).not.toHaveProperty("notMerge");
    const restored = build(["a", "b", "c", "score"]);
    rerender(<EChart option={restored} resolvedTheme="light" accessibleDescription="Joint chart" />);
    expect(instance.setOption).toHaveBeenLastCalledWith(restored, expect.objectContaining({ notMerge: true }));
    expect(echartsMock.init).toHaveBeenCalledTimes(1);
    expect(instance.dispose).not.toHaveBeenCalled();
  });

  it("reports absolute viewport values from data zoom events", () => {
    const onViewportChange = vi.fn();
    render(
      <EChart
        option={option("telemetry")}
        resolvedTheme="light"
        accessibleDescription="Voltage telemetry"
        onViewportChange={onViewportChange}
      />,
    );
    const handler = echartsMock.instances[0]?.handlers.get("datazoom");

    act(() => handler?.({ start: 10, end: 60 }));
    expect(onViewportChange).toHaveBeenCalledWith(1_100, 1_600);

    act(() => handler?.({ batch: [{ startValue: 1_800, endValue: 1_200 }] }));
    expect(onViewportChange).toHaveBeenLastCalledWith(1_200, 1_800);

    act(() => handler?.({ startValue: null, endValue: null, start: 20, end: 80 }));
    expect(onViewportChange).toHaveBeenCalledTimes(3);
    expect(onViewportChange).toHaveBeenLastCalledWith(1_200, 1_800);
  });

  it("cleans up both Strict Mode instances", async () => {
    const { unmount } = render(
      <StrictMode>
        <EChart
          option={option("telemetry")}
          resolvedTheme="light"
          accessibleDescription="Voltage telemetry"
        />
      </StrictMode>,
    );

    await waitFor(() => expect(echartsMock.init).toHaveBeenCalledTimes(2));
    expect(echartsMock.instances[0]?.dispose).toHaveBeenCalledOnce();
    expect(echartsMock.instances[1]?.dispose).not.toHaveBeenCalled();

    unmount();
    expect(echartsMock.instances[1]?.dispose).toHaveBeenCalledOnce();
  });

  it("moves every pane and the slider to fit the widest value label, and keeps that gutter on updates", () => {
    const withLabels = (labels: string[]) => ({
      eachComponent: (_type: string, visit: (axis: unknown) => void) => visit({
        get: () => undefined,
        axis: { getViewLabels: () => labels.map(formattedLabel => ({ formattedLabel })), getLabelModel: () => ({ getFont: () => "12px sans-serif" }) },
      }),
    });
    const panes = (id: string) => ({
      ...option(id),
      grid: [{ left: 44, top: 26 }, { left: 44, top: 242 }],
      dataZoom: [{ id: "inside", type: "inside" }, { id: "slider", type: "slider", startValue: 1_000 }],
    }) as TelemetryChartOption;
    const { rerender } = render(<EChart option={panes("telemetry")} resolvedTheme="light" accessibleDescription="Rate" />);
    const instance = echartsMock.instances[0]!;
    instance.getModel.mockReturnValue(withLabels(["5.1M", "-100.25K"]));

    act(() => instance.handlers.get("finished")?.(undefined));
    // "-100.25K" is 56 wide here, with the label margin and edge padding: 72.
    expect(instance.setOption).toHaveBeenLastCalledWith({
      grid: [{ left: 72 }, { left: 72 }],
      dataZoom: [{ id: "slider", left: 72 }],
    }, { lazyUpdate: true });
    const calls = instance.setOption.mock.calls.length;
    act(() => instance.handlers.get("finished")?.(undefined));
    expect(instance.setOption).toHaveBeenCalledTimes(calls);

    rerender(<EChart option={panes("telemetry")} resolvedTheme="light" accessibleDescription="Rate" />);
    const updated = instance.setOption.mock.lastCall?.[0] as { grid: Array<{ left: number; top: number }>; dataZoom: unknown[] };
    expect(updated.grid).toEqual([{ left: 72, top: 26 }, { left: 72, top: 242 }]);
    expect(updated.dataZoom).toEqual([{ id: "inside", type: "inside" }, { id: "slider", type: "slider", startValue: 1_000, left: 72 }]);
  });
});
