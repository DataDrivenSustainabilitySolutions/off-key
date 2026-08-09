import { useEffect, type ComponentProps } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EChart } from "@/components/EChart";
import { ThemeProvider } from "@/components/theme-provider";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";

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

type InspectableOption = {
  grid: Array<{ left?: number | string; right?: number | string }>;
  xAxis: Array<{
    id?: string;
    gridIndex?: number;
    min?: number;
    max?: number;
    name?: string;
  }>;
  dataZoom: Array<{ startValue?: number; endValue?: number }>;
  series: Array<{
    id: string;
    data: Array<[number, number | null]>;
    lineStyle?: { color?: string };
  }>;
};

const inspectOption = (): InspectableOption =>
  chartMock.latestProps?.option as unknown as InspectableOption;

const operationalService: ActiveService = {
  id: "service-adaptive",
  container_id: "container-1",
  container_name: "radar-adaptive",
  mqtt_topics: ["device/evCharger/charger-1/voltage"],
  status: true,
  monitoring_strategy: "adaptive_stream",
  operational_status: {
    stage: "operational",
    message_count: 2,
    processed_message_count: 2,
    is_stale: false,
  },
};

const scoreEvidence = (timestamp: string, sequenceNumber: number): MonitoringChartEvidence => ({
  service_id: operationalService.id,
  timestamp,
  sequence_number: sequenceNumber,
  sensor_set: ["voltage"],
  input_timestamps: { voltage: timestamp },
  strategy: "adaptive_stream",
  anomaly_score: sequenceNumber,
  restarted_martingale: null,
  threshold: 5,
  alarm: false,
  created: timestamp,
});

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

  it("replaces delayed pending telemetry without moving an inspected viewport", async () => {
    const firstTime = "2026-07-27T10:00:00Z";
    const secondTime = "2026-07-27T10:02:00Z";
    const firstEvidence = scoreEvidence(firstTime, 1);
    const { rerender } = render(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={telemetry(secondTime)}
          evidence={[firstEvidence]}
          monitoringService={operationalService}
        />
      </ThemeProvider>,
    );
    showChart();
    fireEvent.click(await screen.findByRole("img"));

    expect(
      inspectOption().series.find(({ id }) => id === "pending-telemetry")?.data,
    ).toEqual([[Date.parse(secondTime), 231]]);
    expect(screen.getByText("1 awaiting score")).toBeTruthy();

    rerender(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={telemetry(secondTime)}
          evidence={[firstEvidence, scoreEvidence(secondTime, 2)]}
          monitoringService={operationalService}
        />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(
        inspectOption().series.find(({ id }) => id === "pending-telemetry"),
      ).toBeUndefined(),
    );
    expect(inspectOption().dataZoom[0]).toMatchObject({
      startValue: 1_000,
      endValue: 2_000,
    });
  });

  it("never substitutes historical evidence for the active monitoring service", async () => {
    const historicalEvidence = {
      ...scoreEvidence("2026-07-27T10:00:00Z", 1),
      service_id: "service-historical",
    };
    const { rerender } = render(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={telemetry()}
          evidence={[historicalEvidence]}
          monitoringService={operationalService}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText("Awaiting first score")).toBeTruthy();
    expect(screen.queryByText("Adaptive scores")).toBeNull();
    showChart();
    await screen.findByRole("img");
    expect(inspectOption().series.map(({ id }) => id)).toEqual(["telemetry"]);

    rerender(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={telemetry()}
          evidence={[
            historicalEvidence,
            scoreEvidence("2026-07-27T10:02:00Z", 2),
          ]}
          monitoringService={operationalService}
        />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(inspectOption().series.map(({ id }) => id)).toEqual([
        "telemetry",
        "adaptive-score:service-adaptive",
        "adaptive-threshold:service-adaptive",
      ]),
    );
  });

  it("sizes panes from renderable evidence rather than buffered rows", async () => {
    const bufferedEvidence = scoreEvidence("2026-07-27T10:01:00Z", 1);
    render(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={telemetry()}
          evidence={[bufferedEvidence]}
          monitoringService={operationalService}
        />
      </ThemeProvider>,
    );

    const placeholder = document.querySelector('div[aria-hidden="true"]');
    expect(placeholder?.className).toContain("h-[420px]");
    expect(screen.queryByText("Adaptive scores")).toBeNull();

    showChart();
    await screen.findByRole("img");
    expect(inspectOption().grid).toHaveLength(1);
  });

  it("cancels a queued viewport update when returning to live", async () => {
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrameId = 1;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      const frameId = nextFrameId;
      nextFrameId += 1;
      frames.set(frameId, callback);
      return frameId;
    });
    vi.stubGlobal("cancelAnimationFrame", (frameId: number) => {
      frames.delete(frameId);
    });

    render(renderChart(telemetry()));
    showChart();
    fireEvent.click(await screen.findByRole("img"));
    fireEvent.click(screen.getByRole("button", { name: "Return to live" }));

    act(() => {
      for (const callback of frames.values()) callback(performance.now());
      frames.clear();
    });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Return to live" })).toBeNull(),
    );
  });

  it("uses the teal GUI accent primary color for the original telemetry series", async () => {
    render(renderChart(telemetry()));
    await waitFor(() =>
      expect(document.querySelector('[data-slot="card"]')).not.toBeNull(),
    );
    showChart();
    await screen.findByRole("img");

    await waitFor(() => {
      const option = inspectOption();
      expect(option?.series).toBeDefined();
      const telemetrySeries = option.series.find(({ id }) => id === "telemetry");
      expect(telemetrySeries?.lineStyle?.color).toBe("hsl(173 80% 32%)");
    });
  });

  it("renders the correct placeholder and chart height for multi-pane evidence", async () => {
    const multiPaneTelemetry = telemetry("2026-07-27T10:02:00Z");
    render(
      <ThemeProvider defaultTheme="light">
        <DynamicTelemetryChart
          telemetryData={multiPaneTelemetry}
          evidence={[
            {
              service_id: "service-static",
              timestamp: "2026-07-27T10:00:00Z",
              sequence_number: 1,
              sensor_set: ["voltage"],
              input_timestamps: { voltage: "2026-07-27T10:00:00Z" },
              strategy: "static_baseline",
              restarted_martingale: 10,
              threshold: 5,
              alarm: false,
              created: "2026-07-27T10:00:00Z",
            },
            {
              service_id: "service-adaptive",
              timestamp: "2026-07-27T10:02:00Z",
              sequence_number: 1,
              sensor_set: ["voltage"],
              input_timestamps: { voltage: "2026-07-27T10:02:00Z" },
              strategy: "adaptive_stream",
              restarted_martingale: null,
              anomaly_score: 1.5,
              threshold: 2,
              alarm: false,
              created: "2026-07-27T10:02:00Z",
            },
          ]}
        />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(document.querySelector('[data-slot="card"]')).not.toBeNull(),
    );
    const card = document.querySelector('[data-slot="card"]');
    const placeholder = card?.querySelector('div[aria-hidden="true"]');
    expect(placeholder?.className).toContain("h-[680px]");

    showChart();
    await screen.findByRole("img");

    await waitFor(() => {
      const option = inspectOption();
      expect(option?.grid).toHaveLength(3);
      expect(option?.xAxis).toHaveLength(3);
    });
  });
});
