import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Details from "../pages/Details";

const mockLoadAllTelemetryTypes = vi.fn(() => Promise.resolve());
const mockLoadAnomalies = vi.fn(() => Promise.resolve());
const mockSyncTelemetryShort = vi.fn(() => Promise.resolve());
const mockUseFetch = vi.fn();

vi.mock("../dataFetch/UseFetch", () => ({
  useFetch: () => mockUseFetch(),
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

vi.mock("../components/DynamicTelemetryChart", () => ({
  default: ({ telemetryData }: { telemetryData: { type: string } }) => (
    <div data-testid="telemetry-chart">{telemetryData.type}</div>
  ),
}));

function renderDetails() {
  return render(
    <MemoryRouter initialEntries={["/details/123"]}>
      <Routes>
        <Route path="/details/:chargerId" element={<Details />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("<Details />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFetch.mockReturnValue({
      allTelemetryMap: {
        "123": [
          {
            type: "controllerCpuUsage",
            category: "cpu",
            data: [{ timestamp: "2026-04-14T10:00:00Z", value: 42 }],
          },
          {
            type: "systemVoltage",
            category: "system",
            data: [{ timestamp: "2026-04-14T10:00:00Z", value: 12 }],
          },
        ],
      },
      anomaliesMap: { "123": [] },
      loadAllTelemetryTypes: mockLoadAllTelemetryTypes,
      loadAnomalies: mockLoadAnomalies,
      syncTelemetryShort: mockSyncTelemetryShort,
    });
  });

  it("loads telemetry data and renders category sections", async () => {
    renderDetails();

    await waitFor(() => {
      expect(mockLoadAllTelemetryTypes).toHaveBeenCalledWith("123");
      expect(mockLoadAnomalies).toHaveBeenCalledWith("123");
    });
    expect(screen.getByText(/cpu metrics/i)).toBeTruthy();
    expect(screen.getByText(/system metrics/i)).toBeTruthy();
    expect(screen.getAllByTestId("telemetry-chart")).toHaveLength(2);
  });

  it("renders the monitoring link for the selected charger", async () => {
    renderDetails();

    const link = await screen.findByRole("link", { name: /monitoring/i });
    expect(link.getAttribute("href")).toBe("/monitoring/123");
  });

  it("shows the empty state when no telemetry is available", async () => {
    mockUseFetch.mockReturnValue({
      allTelemetryMap: { "123": [] },
      anomaliesMap: { "123": [] },
      loadAllTelemetryTypes: mockLoadAllTelemetryTypes,
      loadAnomalies: mockLoadAnomalies,
      syncTelemetryShort: mockSyncTelemetryShort,
    });

    renderDetails();

    expect(
      await screen.findByText(/no telemetry data available for this charger/i)
    ).toBeTruthy();
  });
});
