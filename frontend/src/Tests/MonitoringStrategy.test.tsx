import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Monitoring from "../pages/Monitoring";

const mockPost = vi.fn(() => Promise.resolve({}));
const mockGet = vi.fn();
const mockDelete = vi.fn();

vi.mock("../lib/api-client", () => ({
  apiUtils: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

const modelCatalog = {
  pyod_iforest: {
    strategy: "static_baseline",
    parameters: {
      properties: {
        n_estimators: { type: "integer", default: 100 },
        contamination: { type: "number", default: 0.1 },
      },
    },
  },
};

function renderMonitoring() {
  return render(
    <MemoryRouter initialEntries={["/monitoring/charger-1"]}>
      <Routes>
        <Route path="/monitoring/:chargerId" element={<Monitoring />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("<Monitoring /> static setup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/models")) return Promise.resolve(modelCatalog);
      if (url.endsWith("/type")) return Promise.resolve(["L1", "L2", "L3"]);
      return Promise.resolve([]);
    });
  });

  it("submits the static baseline contract", async () => {
    renderMonitoring();

    await screen.findByText(/topic input mode/i);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "direct_patterns" },
    });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "charger/charger-1/live-telemetry/L1" },
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
      epsilon: 0.5,
      restarted_ville_threshold: 100,
    });
    expect(payload.adaptive_stream_config).toBeUndefined();
    expect(payload.preprocessing_steps).toBeUndefined();
  });

  it("submits concrete sensor topics for multivariate alignment", async () => {
    renderMonitoring();

    await screen.findByText(/topic input mode/i);
    await screen.findAllByText("L1");
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];

    expect(payload.mqtt_topics).toEqual([
      "charger/charger-1/live-telemetry/L1",
      "charger/charger-1/live-telemetry/L2",
      "charger/charger-1/live-telemetry/L3",
    ]);
    expect(payload.performance_config.alignment_mode).toBe("strict_barrier");
  });

  it("submits editable epsilon with the fixed native threshold", async () => {
    renderMonitoring();

    fireEvent.change(await screen.findByDisplayValue("360"), {
      target: { value: "400" },
    });
    fireEvent.click(screen.getByRole("button", { name: /show advanced settings/i }));
    fireEvent.change(screen.getByDisplayValue("0.5"), {
      target: { value: "0.75" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = mockPost.mock.calls[0][1];
    expect(payload.static_baseline_config.calibration_window_size).toBe(400);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      method: "power",
      epsilon: 0.75,
      restarted_ville_threshold: 100,
    });
  });

  it("lets numeric fields be cleared while editing", async () => {
    renderMonitoring();

    const trainingInput = await screen.findByDisplayValue("1200");
    fireEvent.change(trainingInput, { target: { value: "" } });
    expect((trainingInput as HTMLInputElement).value).toBe("");
  });

  it("blocks below-min training sizes until fixed", async () => {
    renderMonitoring();

    const trainingInput = await screen.findByDisplayValue("1200");
    fireEvent.change(trainingInput, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    expect(mockPost).not.toHaveBeenCalled();
    expect(await screen.findByText("Training samples must be at least 20.")).toBeTruthy();

    fireEvent.change(trainingInput, { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1].static_baseline_config.training_window_size).toBe(2000);
  });

  it("keeps invalid detector integer drafts visible and blocks submit", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /show advanced settings/i }));
    const estimatorsInput = await screen.findByDisplayValue("100");
    fireEvent.change(estimatorsInput, { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    expect((estimatorsInput as HTMLInputElement).value).toBe("1.5");
    expect(mockPost).not.toHaveBeenCalled();
    expect(await screen.findByText("N Estimators must be an integer.")).toBeTruthy();

    fireEvent.change(estimatorsInput, { target: { value: "101" } });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1].static_baseline_config.model_params.n_estimators).toBe(101);
  });

  it("renders dynamic as a non-interactive facade with no adaptive controls", async () => {
    renderMonitoring();

    expect(await screen.findByText("Temporally dependent streams")).toBeTruthy();
    expect(screen.getByText("Coming later")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /dynamic/i })).toBeNull();
    expect(screen.queryByText(/dynamic model/i)).toBeNull();
    expect(screen.queryByText(/FDR Control/i)).toBeNull();
    expect(screen.getByText(/Fixed Ville threshold/i)).toBeTruthy();
  });

  it("disables sensors claimed by an overlapping active service", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/models")) return Promise.resolve(modelCatalog);
      if (url.includes("/monitors/all")) {
        return Promise.resolve([{
          id: 7,
          container_name: "radar-existing",
          mqtt_topics: ["charger/charger-1/live-telemetry/L1"],
          status: "running",
        }]);
      }
      if (url.endsWith("/type")) return Promise.resolve(["L1", "L2", "L3"]);
      return Promise.resolve([]);
    });
    renderMonitoring();

    expect(await screen.findByText("Assigned to radar-existing")).toBeTruthy();
    const l1Checkbox = screen.getByText("Assigned to radar-existing").closest("label")?.querySelector("input");
    expect((l1Checkbox as HTMLInputElement | undefined)?.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1].mqtt_topics).toEqual([
      "charger/charger-1/live-telemetry/L2",
      "charger/charger-1/live-telemetry/L3",
    ]);
  });
});
