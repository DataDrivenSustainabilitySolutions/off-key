import { StrictMode } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TelemetryChartOption } from "@/lib/telemetry-chart";

const echartsMock = vi.hoisted(() => {
  const instances: Array<{
    setOption: ReturnType<typeof vi.fn>;
    setTheme: ReturnType<typeof vi.fn>;
    resize: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    off: ReturnType<typeof vi.fn>;
    getOption: ReturnType<typeof vi.fn>;
    handlers: Map<string, (payload: unknown) => void>;
  }> = [];
  const init = vi.fn(() => {
    const handlers = new Map<string, (payload: unknown) => void>();
    const instance = {
      setOption: vi.fn(),
      setTheme: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      on: vi.fn((event: string, handler: (payload: unknown) => void) => {
        handlers.set(event, handler);
      }),
      off: vi.fn((event: string) => handlers.delete(event)),
      getOption: vi.fn(() => ({
        xAxis: [{ min: 1_000, max: 2_000 }],
        legend: [{ selected: { Voltage: false } }],
      })),
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
}));
vi.mock("echarts/charts", () => ({ LineChart: {}, ScatterChart: {} }));
vi.mock("echarts/components", () => ({
  AriaComponent: {},
  AxisPointerComponent: {},
  DataZoomInsideComponent: {},
  DataZoomSliderComponent: {},
  GridComponent: {},
  LegendScrollComponent: {},
  MarkAreaComponent: {},
  MarkLineComponent: {},
  MarkPointComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

import { EChart } from "@/components/EChart";

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

afterEach(() => vi.unstubAllGlobals());

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
});
