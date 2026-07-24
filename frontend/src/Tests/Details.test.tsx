import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Details from "../pages/Details";

const mockLoadAllTelemetryTypes = vi.fn();
const mockLoadAnomalies = vi.fn();
const mockApiGet = vi.fn(() => Promise.resolve([]));

vi.mock("../lib/api-client", () => ({
  apiUtils: { get: (...args: unknown[]) => mockApiGet(...args) },
}));

vi.mock("../lib/charger-api", () => ({
  getAllTelemetryData: (...args: unknown[]) => mockLoadAllTelemetryTypes(...args),
  getAnomalies: (...args: unknown[]) => mockLoadAnomalies(...args),
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
    mockApiGet.mockResolvedValue([]);
    mockLoadAllTelemetryTypes.mockResolvedValue([
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
    ]);
    mockLoadAnomalies.mockResolvedValue([]);
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
    mockLoadAllTelemetryTypes.mockResolvedValue([]);

    renderDetails();

    expect(
      await screen.findByText(/no telemetry data available for this charger/i)
    ).toBeTruthy();
  });
});
