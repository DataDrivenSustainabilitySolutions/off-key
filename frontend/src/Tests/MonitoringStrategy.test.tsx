import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { parseNumericInput } from "../lib/monitoring-config";
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

  it("does not truncate invalid numeric config input", () => {
    expect(parseNumericInput("1.5", "integer")).toBe("");
    expect(parseNumericInput("12abc", "number")).toBe("");
    expect(parseNumericInput("1e2", "number")).toBe(100);
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
    expect(payload.static_baseline_config.training_window_size).toBe(1200);
    expect(payload.static_baseline_config.fdr_config.method).toBe("saffron");
    expect(payload.adaptive_stream_config).toBeUndefined();
  });

  it("submits concrete static sensor topics for multivariate alignment", async () => {
    renderMonitoring();

    await screen.findByText(/topic input mode/i);
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];

    expect(payload.strategy).toBe("static_baseline");
    expect(payload.mqtt_topics).toEqual([
      "charger/charger-1/live-telemetry/L1",
      "charger/charger-1/live-telemetry/L2",
      "charger/charger-1/live-telemetry/L3",
    ]);
    expect(payload.performance_config.alignment_mode).toBe("strict_barrier");
  });

  it("submits a naive static FDR cutoff payload without SAFFRON validation", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    fireEvent.change(screen.getByDisplayValue("0.025"), {
      target: { value: "0.05" },
    });
    fireEvent.change(screen.getByDisplayValue("SAFFRON"), {
      target: { value: "naive" },
    });
    fireEvent.change(screen.getByDisplayValue("0.05"), {
      target: { value: "0.02" },
    });

    expect(screen.queryByText(/^Alpha$/i)).toBeNull();
    expect(screen.queryByText(/^Wealth$/i)).toBeNull();
    expect(screen.queryByText(/^Lambda$/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];

    expect(payload.static_baseline_config.fdr_config).toEqual({
      method: "naive",
      cutoff: 0.02,
    });
  });

  it("clamps stale SAFFRON wealth when switching back from naive FDR", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    fireEvent.change(screen.getByDisplayValue("0.025"), {
      target: { value: "0.05" },
    });
    fireEvent.change(screen.getByDisplayValue("SAFFRON"), {
      target: { value: "naive" },
    });
    fireEvent.change(screen.getByDisplayValue("Naive p-value cutoff"), {
      target: { value: "saffron" },
    });

    expect(await screen.findByDisplayValue("0.025")).toBeTruthy();
  });

  it("switches to the dynamic menu without losing the static menu", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /dynamic/i }));

    expect(await screen.findByText(/dynamic model/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^static$/i }));

    expect(await screen.findByText(/static detector/i)).toBeTruthy();
  });

  it("preserves static draft values while viewing the adaptive menu", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    const staticWindowInput = await screen.findByDisplayValue("1200");
    fireEvent.change(staticWindowInput, { target: { value: "2400" } });

    fireEvent.click(screen.getByRole("button", { name: /dynamic/i }));
    expect(await screen.findByText(/dynamic model/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^static$/i }));

    expect(await screen.findByDisplayValue("2400")).toBeTruthy();
  });
});
