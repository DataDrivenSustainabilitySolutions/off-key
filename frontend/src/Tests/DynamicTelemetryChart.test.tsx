import { useEffect, type ComponentProps } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EChart } from "@/components/EChart";
import { ThemeProvider } from "@/components/theme-provider";

const chartMock = vi.hoisted(() => ({
  mounted: vi.fn(),
  disposed: vi.fn(),
  latestProps: undefined as ComponentProps<typeof EChart> | undefined,
}));

vi.mock("@/components/EChart", () => ({
  EChart: (props: ComponentProps<typeof EChart>) => {
    chartMock.latestProps = props;
    useEffect(() => {
      chartMock.mounted();
      return () => chartMock.disposed();
    }, []);
    return (
      <button
        type="button"
        role="img"
        aria-label={props.accessibleDescription}
        onClick={() => props.onViewportChange?.(1_000, 2_000)}
      >
        Inspect chart
      </button>
    );
  },
}));

import { DynamicTelemetryChart } from "@/components/DynamicTelemetryChart";

let intersectionCallback: IntersectionObserverCallback | undefined;

class MockIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = "600px 0px";
  readonly scrollMargin = "0px";
  readonly thresholds = [0];
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = () => [];

  constructor(callback: IntersectionObserverCallback) {
    intersectionCallback = callback;
  }
}

const telemetry = (latestTimestamp = "2026-07-27T10:02:00Z") => ({
  type: "voltage",
  category: "system" as const,
  unit: "V",
  data: [
    { timestamp: "2026-07-27T10:00:00Z", value: 230 },
    { timestamp: latestTimestamp, value: 231 },
  ],
});

const renderChart = (
  telemetryData: ReturnType<typeof telemetry> | { type: string; category: "system"; data: [] },
) => (
  <ThemeProvider defaultTheme="light">
    <DynamicTelemetryChart telemetryData={telemetryData} />
  </ThemeProvider>
);

const showChart = () => {
  const target = document.querySelector('[data-slot="card"]');
  if (!target || !intersectionCallback) throw new Error("Chart observer not ready");
  act(() =>
    intersectionCallback?.(
      [{ isIntersecting: true, target } as IntersectionObserverEntry],
      {} as IntersectionObserver,
    ),
  );
};

const inspectOption = (): {
  dataZoom: Array<{ startValue?: number; endValue?: number }>;
} => chartMock.latestProps?.option as unknown as {
  dataZoom: Array<{ startValue?: number; endValue?: number }>;
};

beforeEach(() => {
  localStorage.clear();
  intersectionCallback = undefined;
  chartMock.mounted.mockClear();
  chartMock.disposed.mockClear();
  chartMock.latestProps = undefined;
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
});

afterEach(() => vi.unstubAllGlobals());

describe("DynamicTelemetryChart", () => {
  it("observes a chart that first renders without telemetry data", async () => {
    const { container, rerender } = render(
      renderChart({ type: "voltage", category: "system", data: [] }),
    );

    rerender(renderChart(telemetry()));

    await waitFor(() => {
      const card = container.querySelector('[data-slot="card"]');
      expect(card).not.toBeNull();
    });
  });

  it("mounts only while visible and expanded, disposing on both exits", async () => {
    render(renderChart(telemetry()));
    expect(screen.queryByRole("img")).toBeNull();

    showChart();
    await screen.findByRole("img");
    expect(chartMock.mounted).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Collapse chart" }));
    expect(chartMock.disposed).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Expand chart" }));
    await screen.findByRole("img");
    expect(chartMock.mounted).toHaveBeenCalledTimes(2);

    const target = document.querySelector('[data-slot="card"]');
    act(() =>
      intersectionCallback?.(
        [{ isIntersecting: false, target } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      ),
    );
    expect(chartMock.disposed).toHaveBeenCalledTimes(2);
  });

  it("preserves an inspected viewport across polling and returns to live", async () => {
    const { rerender } = render(renderChart(telemetry()));
    showChart();
    fireEvent.click(await screen.findByRole("img"));

    expect(screen.getByText("Inspection paused")).toBeTruthy();
    expect(inspectOption().dataZoom[0]).toMatchObject({
      startValue: 1_000,
      endValue: 2_000,
    });

    rerender(renderChart(telemetry("2026-07-27T10:03:00Z")));
    expect(await screen.findByText("New data available")).toBeTruthy();
    expect(inspectOption().dataZoom[0]).toMatchObject({
      startValue: 1_000,
      endValue: 2_000,
    });

    fireEvent.click(screen.getByRole("button", { name: "Return to live" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Return to live" })).toBeNull(),
    );
    expect(inspectOption().dataZoom[0]?.endValue).toBe(
      Date.parse("2026-07-27T10:03:00Z"),
    );
  });

  it("treats date controls as authoritative and exposes timezone/summary text", async () => {
    render(renderChart(telemetry()));
    showChart();
    fireEvent.click(await screen.findByRole("img"));
    expect(screen.getByRole("button", { name: "Return to live" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Past hour" }));
    expect(screen.queryByRole("button", { name: "Return to live" })).toBeNull();
    expect(screen.getByText(/Local time zone:/u)).toBeTruthy();
    expect(screen.getByText(/Current Voltage: 231 V at/u)).toBeTruthy();
  });
});
