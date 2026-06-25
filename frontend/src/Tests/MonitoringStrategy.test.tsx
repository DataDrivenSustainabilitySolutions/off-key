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
    expect(payload.static_baseline_config.training_window_size).toBe(1200);
    expect(payload.static_baseline_config.calibration_window_size).toBe(360);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      method: "power",
      alpha: 0.01,
      epsilon: 0.5,
    });
    expect(payload.static_baseline_config.fdr_config).toBeUndefined();
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

  it("submits static martingale alarm settings", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    fireEvent.change(screen.getByDisplayValue("360"), {
      target: { value: "400" },
    });
    fireEvent.change(screen.getByDisplayValue("0.01"), {
      target: { value: "0.02" },
    });
    fireEvent.change(screen.getByDisplayValue("0.5"), {
      target: { value: "0.75" },
    });

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];

    expect(payload.static_baseline_config.calibration_window_size).toBe(400);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      method: "power",
      alpha: 0.02,
      epsilon: 0.75,
    });
  });

  it("lets static numeric fields be cleared while editing", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    const staticWindowInput = await screen.findByDisplayValue("1200");

    fireEvent.change(staticWindowInput, { target: { value: "" } });

    expect((staticWindowInput as HTMLInputElement).value).toBe("");
  });

  it("blocks below-min static values until fixed", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    const staticWindowInput = await screen.findByDisplayValue("1200");

    fireEvent.change(staticWindowInput, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    expect((staticWindowInput as HTMLInputElement).value).toBe("10");
    expect(mockPost).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Training window size must be at least 20.")
    ).toBeTruthy();

    fireEvent.change(staticWindowInput, { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];
    expect(payload.static_baseline_config.training_window_size).toBe(2000);
  });

  it("keeps invalid detector integer drafts visible and blocks submit", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));
    const estimatorsInput = await screen.findByDisplayValue("100");

    fireEvent.change(estimatorsInput, { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    expect((estimatorsInput as HTMLInputElement).value).toBe("1.5");
    expect(mockPost).not.toHaveBeenCalled();
    expect(await screen.findByText("n_estimators must be an integer.")).toBeTruthy();

    fireEvent.change(estimatorsInput, { target: { value: "101" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];
    expect(payload.static_baseline_config.model_params.n_estimators).toBe(101);
  });

  it("does not render legacy static FDR controls", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show configuration/i }));

    expect(screen.queryByText(/FDR Control/i)).toBeNull();
    expect(screen.queryByDisplayValue("SAFFRON")).toBeNull();
    expect(screen.queryByDisplayValue("Naive p-value cutoff")).toBeNull();
    expect(await screen.findByText(/Martingale Alarm/i)).toBeTruthy();
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
