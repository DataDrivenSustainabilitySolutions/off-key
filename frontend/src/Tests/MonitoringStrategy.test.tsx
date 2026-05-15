import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Monitoring from "../pages/Monitoring";

const mockPost = vi.fn(() => Promise.resolve({}));
const mockGet = vi.fn();
const mockDelete = vi.fn();
const mockLoadAllTelemetryTypes = vi.fn(() => Promise.resolve());

vi.mock("../lib/api-client", () => ({
  apiUtils: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}));

vi.mock("../dataFetch/UseFetch", () => ({
  useFetch: () => ({
    allTelemetryMap: {
      "charger-1": [
        { type: "L1", data: [] },
        { type: "L2", data: [] },
        { type: "L3", data: [] },
      ],
    },
    loadAllTelemetryTypes: mockLoadAllTelemetryTypes,
  }),
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

function renderMonitoring() {
  return render(
    <MemoryRouter initialEntries={["/monitoring/charger-1"]}>
      <Routes>
        <Route path="/monitoring/:chargerId" element={<Monitoring />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("<Monitoring /> strategy setup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/models")) {
        return Promise.resolve({
          pyod_iforest: {
            strategy: "static_baseline",
            parameters: {
              properties: {
                n_estimators: { type: "integer", default: 100 },
                contamination: { type: "number", default: 0.1 },
              },
            },
          },
          knn: {
            strategy: "adaptive_stream",
            parameters: {
              properties: {
                k: { type: "integer", default: 5 },
              },
            },
          },
        });
      }
      if (url.includes("/preprocessors")) {
        return Promise.resolve({});
      }
      return Promise.resolve([]);
    });
  });

  it("submits a static baseline payload from the static menu", async () => {
    renderMonitoring();

    await screen.findByText(/topic input mode/i);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "direct_patterns" },
    });

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];

    expect(payload.strategy).toBe("static_baseline");
    expect(payload.model_type).toBe("pyod_iforest");
    expect(payload.static_baseline_config.training_window_size).toBe(1000);
    expect(payload.static_baseline_config.fdr_config.method).toBe("saffron");
    expect(payload.adaptive_stream_config).toBeUndefined();
  });

  it("switches to the adaptive stream menu without losing the static menu", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /adaptive stream/i }));

    expect(await screen.findByText(/adaptive algorithm/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /static baseline/i }));

    expect(await screen.findByText(/static detector/i)).toBeTruthy();
  });

  it("preserves static draft values while viewing the adaptive menu", async () => {
    renderMonitoring();

    const staticWindowInput = await screen.findByDisplayValue("1000");
    fireEvent.change(staticWindowInput, { target: { value: "2400" } });

    fireEvent.click(screen.getByRole("button", { name: /adaptive stream/i }));
    expect(await screen.findByText(/adaptive algorithm/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /static baseline/i }));

    expect(await screen.findByDisplayValue("2400")).toBeTruthy();
  });
});
