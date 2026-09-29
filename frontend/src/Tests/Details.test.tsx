import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Details from "../pages/Details";
import type { ChartNavigationState } from "../lib/telemetry-chart";

const mockLoadAllTelemetryTypes = vi.fn<
  (...args: unknown[]) => Promise<unknown[]>
>(() => Promise.resolve([]));
const mockLoadAnomalies = vi.fn<
  (...args: unknown[]) => Promise<unknown[]>
>(() => Promise.resolve([]));
const mockApiGet = vi.fn<(...args: unknown[]) => Promise<unknown[]>>(() =>
  Promise.resolve([])
);
const mockChartAnomalyProps: unknown[][] = [];

vi.mock("../lib/api-client", () => ({
  apiUtils: { get: (...args: unknown[]) => mockApiGet(...args) },
}));

vi.mock("../lib/charger-api", () => ({
  getAllTelemetryData: (...args: unknown[]) => mockLoadAllTelemetryTypes(...args),
  getAnomalies: (...args: unknown[]) => mockLoadAnomalies(...args),
  getTelemetryCursor: () => undefined,
  mergeTelemetryData: (_current: unknown, incoming: unknown) => incoming,
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

vi.mock("../components/DynamicTelemetryChart", () => ({
  default: ({
    telemetryData,
    anomalies,
    navigationState,
    onNavigationStateChange,
  }: {
    telemetryData: { type: string };
    anomalies: unknown[];
    navigationState: ChartNavigationState;
    onNavigationStateChange: (
      telemetryType: string,
      state: ChartNavigationState,
    ) => void;
  }) => {
    mockChartAnomalyProps.push(anomalies);
    return (
      <div data-testid="telemetry-chart">
        {telemetryData.type}
        <output data-testid={`navigation-${telemetryData.type}`}>
          {JSON.stringify(navigationState)}
        </output>
        <button
          type="button"
          onClick={() =>
            onNavigationStateChange(telemetryData.type, {
              range: {},
              viewport: {
                mode: "absolute",
                startMs:
                  telemetryData.type === "controllerCpuUsage" ? 1_000 : 3_000,
                endMs:
                  telemetryData.type === "controllerCpuUsage" ? 2_000 : 4_000,
              },
              inspectionDataEndMs: 5_000,
            })
          }
        >
          Navigate {telemetryData.type}
        </button>
      </div>
    );
  },
}));

function renderDetails(initialEntry = "/details/123") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/details/:chargerId" element={<Details />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("<Details />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockChartAnomalyProps.length = 0;
    mockApiGet.mockResolvedValue([]);
    mockLoadAllTelemetryTypes.mockResolvedValue([
      {
        type: "controllerCpuUsage",
        category: "Processor",
        data: [{ timestamp: "2026-04-14T10:00:00Z", value: 42 }],
      },
      {
        type: "systemVoltage",
        category: "Voltage",
        data: [{ timestamp: "2026-04-14T10:00:00Z", value: 12 }],
      },
    ]);
    mockLoadAnomalies.mockResolvedValue([]);
  });

  it("loads telemetry data and renders catalog category sections", async () => {
    renderDetails();

    await waitFor(() => {
      expect(mockLoadAllTelemetryTypes).toHaveBeenCalledWith(
        "123",
        expect.any(AbortSignal),
      );
      expect(mockLoadAnomalies).toHaveBeenCalledWith(
        "123",
        expect.any(AbortSignal),
      );
    });
    expect(screen.getByRole("heading", { name: "Processor Metrics" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Voltage Metrics" })).toBeTruthy();
    expect(screen.queryByText(/other metrics/i)).toBeNull();
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "All categories (2)" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Showing 2 of 2 charts")).toBeTruthy();
  });

  it("filters by any selected catalog category and shows counts per category", async () => {
    mockLoadAllTelemetryTypes.mockResolvedValue([
      ["currentAc", "Charging diagnostics"],
      ["currentDc", "Charging diagnostics"],
      ["inverterTemperature", "Temperature"],
      ["systemVoltage", "Voltage"],
    ].map(([type, category]) => ({
      type,
      category,
      data: [{ timestamp: "2026-04-14T10:00:00Z", value: 12 }],
    })));
    renderDetails();

    fireEvent.click(await screen.findByRole("button", { name: "Charging diagnostics (2)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Charging diagnostics Metrics" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Voltage Metrics" })).toBeNull();
    expect(screen.getByText("Showing 2 of 4 charts")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Temperature (1)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Temperature Metrics" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "All categories (4)" }).getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Charging diagnostics (2)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(1);
    expect(screen.getByText("Showing 1 of 4 charts")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Temperature (1)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "All categories (4)" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("restores category selection from the URL and clears it with All categories", async () => {
    renderDetails("/details/123?category=Voltage");

    const voltage = await screen.findByRole("button", { name: "Voltage (1)" });
    expect(voltage.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "Processor Metrics" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "All categories (2)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
    expect(voltage.getAttribute("aria-pressed")).toBe("false");
  });

  it("keeps filters through polling and restores a hidden chart's inspected range", async () => {
    renderDetails();
    fireEvent.click(await screen.findByRole("button", { name: "Navigate systemVoltage" }));
    fireEvent.click(screen.getByRole("button", { name: "Processor (1)" }));
    expect(screen.queryByTestId("navigation-systemVoltage")).toBeNull();

    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(mockLoadAllTelemetryTypes).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Processor (1)" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByTestId("navigation-systemVoltage")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "All categories (2)" }));
    expect(screen.getByTestId("navigation-systemVoltage").textContent).toContain('"startMs":3000');
  });

  it("allows clearing a category that no longer exists in the catalog", async () => {
    renderDetails("/details/123?category=Removed");

    expect(await screen.findByText(/No charts match the selected categories/)).toBeTruthy();
    expect(screen.queryAllByTestId("telemetry-chart")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "All categories (2)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
  });

  it("renders the monitoring link for the selected charger", async () => {
    renderDetails();

    const link = await screen.findByRole("link", { name: /monitoring/i });
    expect(link.getAttribute("href")).toBe("/monitoring/123");
  });

  it("preserves chart anomaly references across telemetry refreshes", async () => {
    renderDetails();
    await screen.findByText(/processor metrics/i);
    const firstReference = mockChartAnomalyProps[0];

    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(mockChartAnomalyProps.length).toBeGreaterThanOrEqual(4));

    expect(mockChartAnomalyProps.slice(2)).toEqual(
      expect.arrayContaining([firstReference]),
    );
    expect(
      mockChartAnomalyProps.slice(2).every((value) => value === firstReference),
    ).toBe(true);
  });

  it("shows the empty state when no telemetry is available", async () => {
    mockLoadAllTelemetryTypes.mockResolvedValue([]);

    renderDetails();

    expect(
      await screen.findByText(/no telemetry data available for this charger/i)
    ).toBeTruthy();
  });

  it("switches between independent and linked horizontal navigation", async () => {
    renderDetails();
    await screen.findByText(/processor metrics/i);

    const linkButton = screen.getByRole("button", {
      name: "Link chart navigation",
    });
    expect(linkButton.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(
      screen.getByRole("button", { name: "Navigate controllerCpuUsage" }),
    );
    expect(screen.getByTestId("navigation-controllerCpuUsage").textContent).toContain(
      '"startMs":1000',
    );
    expect(screen.getByTestId("navigation-systemVoltage").textContent).toContain(
      '"mode":"live"',
    );

    fireEvent.click(linkButton);
    expect(
      screen.getByRole("button", { name: "Unlink chart navigation" }).getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");
    expect(screen.getByTestId("navigation-systemVoltage").textContent).toContain(
      '"startMs":1000',
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Navigate systemVoltage" }),
    );
    expect(screen.getByTestId("navigation-controllerCpuUsage").textContent).toContain(
      '"startMs":3000',
    );
    expect(screen.getByTestId("navigation-systemVoltage").textContent).toContain(
      '"startMs":3000',
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Unlink chart navigation" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Navigate controllerCpuUsage" }),
    );
    expect(screen.getByTestId("navigation-controllerCpuUsage").textContent).toContain(
      '"startMs":1000',
    );
    expect(screen.getByTestId("navigation-systemVoltage").textContent).toContain(
      '"startMs":3000',
    );
    expect(localStorage.getItem("off-key:details:chart-navigation")).toBe(
      "independent",
    );
  });

  it("restores the linked-navigation preference", async () => {
    localStorage.setItem("off-key:details:chart-navigation", "linked");
    renderDetails();

    const unlinkButton = await screen.findByRole("button", {
      name: "Unlink chart navigation",
    });
    expect(unlinkButton.getAttribute("aria-pressed")).toBe("true");
  });
});
