import { render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DynamicTelemetryChart } from "../components/DynamicTelemetryChart";
import { ThemeProvider } from "../components/theme-provider";

afterEach(() => vi.unstubAllGlobals());

it("observes a chart that first renders without telemetry data", async () => {
  const observe = vi.fn();
  const disconnect = vi.fn();
  class MockIntersectionObserver {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds = [];
    observe = observe;
    disconnect = disconnect;
    unobserve = vi.fn();
    takeRecords = () => [];
  }
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

  const renderChart = (data: Array<{ timestamp: string; value: number }>) => (
    <ThemeProvider defaultTheme="light">
      <DynamicTelemetryChart
        chargerId="charger-1"
        telemetryData={{ type: "voltage", category: "system", data }}
      />
    </ThemeProvider>
  );

  const { container, rerender } = render(renderChart([]));

  rerender(renderChart([{ timestamp: "2026-07-27T10:00:00Z", value: 42.5 }]));

  await waitFor(() => {
    expect(observe).toHaveBeenCalledWith(
      container.querySelector('[data-slot="card"]'),
    );
  });
});
