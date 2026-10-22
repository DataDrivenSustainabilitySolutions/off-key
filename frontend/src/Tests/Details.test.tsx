import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Details from "../pages/Details";
import { CatalogueContext, type CatalogueContextValue } from "../features/workspace/catalogue-context";
import { buildNavigationIndex } from "../features/explorer/navigationIndex";
import { createEmptySystem } from "../features/catalogue/systemDocument";
import type { SystemDocument, SystemRuntime } from "../features/catalogue/systemTypes";
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
      <Link to="/details/456">Switch charger</Link>
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
    expect(screen.getByRole("heading", { name: "Processor" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Voltage" })).toBeTruthy();
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
    expect(screen.getByRole("heading", { name: "Charging diagnostics" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Voltage" })).toBeNull();
    expect(screen.getByText("Showing 2 of 4 charts")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Temperature (1)" }));
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Temperature" })).toBeTruthy();
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
    expect(screen.queryByRole("heading", { name: "Processor" })).toBeNull();

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

  it("is titled by the catalogue entity behind the recorded identity and links to it in Sources", async () => {
    const document: SystemDocument = { ...createEmptySystem(),
      connections: [{ id: "broker", label: "Building broker", protocol: "mqtt", host: "broker.test", port: 1883, transport: "tcp", tls: false }],
      devices: [{ id: "station", label: "Room station", kind: "sensor", connection_id: "broker" }],
      streams: [{ id: "temperature", label: "Air temperature", connection_id: "broker", device_id: "station", topic: "weather/temperature", value_type: "number", category: "Environment" }],
    };
    const runtime = { bindings: { temperature: { connection_id: "broker", entity_id: "123", telemetry_key: "temperature",
      accepted_topic: "telemetry/123/temperature", policy: { mode: "original", interval_seconds: 10 } } } } as unknown as SystemRuntime;
    const index = buildNavigationIndex(document);
    const catalogue = { system: { snapshot: { document, runtime } }, index } as unknown as CatalogueContextValue;
    render(<CatalogueContext.Provider value={catalogue}>
      <MemoryRouter initialEntries={["/details/123"]}><Routes><Route path="/details/:chargerId" element={<Details />} /></Routes></MemoryRouter>
    </CatalogueContext.Provider>);
    expect(await screen.findByRole("heading", { level: 1, name: "Room station" })).toBeTruthy();
    // The binding's entity ID differs from the catalogue device ID, so the link names the catalogue node.
    const station = index.nodes.get(index.objectKeys.get("station")![0]!)!;
    expect(screen.getByRole("link", { name: "View in Sources" }).getAttribute("href")).toBe(`/sources?source=${encodeURIComponent(station.key)}`);
    expect(window.document.title).toBe("Room station · Reporting · Aberration");
  });

  it("falls back to the recorded identity without a catalogue", async () => {
    renderDetails();
    expect(await screen.findByRole("heading", { level: 1, name: "Entity 123" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "View in Sources" }).getAttribute("href")).toBe("/sources");
  });

  it("preserves chart anomaly references across telemetry refreshes", async () => {
    renderDetails();
    await screen.findByRole("heading", { name: "Processor" });
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
      await screen.findByText(/no recorded readings for this entity/i)
    ).toBeTruthy();
  });

  it("preserves charts on a failed refresh and clears the error after recovery", async () => {
    renderDetails();
    await screen.findByRole("heading", { name: "Processor" });
    mockLoadAllTelemetryTypes.mockRejectedValueOnce(new Error("unavailable"));

    document.dispatchEvent(new Event("visibilitychange"));
    expect((await screen.findByRole("alert")).textContent).toContain("Readings could not be refreshed");
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
  });

  it("switches between independent and linked horizontal navigation", async () => {
    renderDetails();
    await screen.findByRole("heading", { name: "Processor" });

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

  it("clears charger data immediately on navigation even if the next load fails", async () => {
    renderDetails();
    fireEvent.click(
      await screen.findByRole("button", { name: "Navigate controllerCpuUsage" }),
    );
    expect(screen.getByTestId("navigation-controllerCpuUsage").textContent).toContain(
      '"startMs":1000',
    );

    mockLoadAllTelemetryTypes.mockRejectedValueOnce(new Error("unavailable"));
    fireEvent.click(screen.getByRole("link", { name: "Switch charger" }));
    expect(screen.queryAllByTestId("telemetry-chart")).toHaveLength(0);
    expect(
      await screen.findByText(/readings could not be loaded/i),
    ).toBeTruthy();
    expect(mockLoadAllTelemetryTypes).toHaveBeenLastCalledWith(
      "456", expect.any(AbortSignal),
    );

    document.dispatchEvent(new Event("visibilitychange"));
    await screen.findByRole("heading", { name: "Processor" });
    expect(screen.getByTestId("navigation-controllerCpuUsage").textContent).toContain(
      '"mode":"live"',
    );
    expect(mockChartAnomalyProps[mockChartAnomalyProps.length - 1]).toEqual([]);
  });
});
