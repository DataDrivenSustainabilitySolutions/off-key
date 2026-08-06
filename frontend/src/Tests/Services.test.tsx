import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Services from "../pages/Services";
import type { ActiveService } from "../types/monitoring";

const mockGet = vi.fn<(endpoint: string) => Promise<unknown>>(() =>
  Promise.resolve([])
);

vi.mock("../lib/api-client", () => ({
  apiUtils: {
    get: (endpoint: string) => mockGet(endpoint),
    delete: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

describe("<Services />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows adaptive mode independently from a running workload status", async () => {
    const adaptiveService: ActiveService = {
      id: "service-1",
      container_id: "container-1",
      container_name: "radar-adaptive-charger-1-123",
      mqtt_topics: ["charger/charger-1/live-telemetry/random"],
      status: true,
      docker_status: "running",
      monitoring_strategy: "adaptive_stream",
      model_type: "aberrant_knn",
      operational_status: {
        stage: "operational",
        message_count: 1156,
        processed_message_count: 1156,
        is_stale: false,
      },
    };
    mockGet.mockResolvedValue([adaptiveService]);

    render(
      <MemoryRouter initialEntries={["/services"]}>
        <Services />
      </MemoryRouter>
    );

    const serviceName = await screen.findByText(adaptiveService.container_name);
    const row = serviceName.closest("tr");
    expect(row).not.toBeNull();

    const serviceRow = within(row as HTMLTableRowElement);
    expect(serviceRow.getByText("Adaptive")).toBeTruthy();
    expect(serviceRow.getByText("Running")).toBeTruthy();
    expect(serviceRow.queryByText("Retired")).toBeNull();
  });
});
