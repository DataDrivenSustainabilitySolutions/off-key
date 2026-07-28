import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../lib/api-client";
import Monitoring from "../pages/Monitoring";
import type { AnomalyDetectionRequest } from "../types/monitoring";

const mockPost = vi.fn<
  (
    endpoint: string,
    payload: AnomalyDetectionRequest,
    options?: ApiRequestOptions
  ) => Promise<unknown>
>(() => Promise.resolve({}));
const mockGet = vi.fn<
  (endpoint: string, options?: ApiRequestOptions) => Promise<unknown>
>(() => Promise.resolve([]));
const mockDelete = vi.fn<
  (
    endpoint: string,
    data?: unknown,
    options?: ApiRequestOptions
  ) => Promise<unknown>
>(() => Promise.resolve({}));

vi.mock("../lib/api-client", () => ({
  apiUtils: {
    get: (endpoint: string, options?: ApiRequestOptions) =>
      mockGet(endpoint, options),
    post: (
      endpoint: string,
      payload: AnomalyDetectionRequest,
      options?: ApiRequestOptions
    ) => mockPost(endpoint, payload, options),
    delete: (endpoint: string, data?: unknown, options?: ApiRequestOptions) =>
      mockDelete(endpoint, data, options),
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

const getSubmittedPayload = (): AnomalyDetectionRequest => {
  const latestCall = mockPost.mock.calls[mockPost.mock.calls.length - 1];
  const payload = latestCall?.[1];
  if (!payload) {
    throw new Error("Expected monitoring request payload");
  }
  return payload;
};

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
    const [topicModeSelect] = screen.getAllByRole("combobox");
    if (!topicModeSelect) throw new Error("Expected topic mode selector");
    fireEvent.change(topicModeSelect, {
      target: { value: "direct_patterns" },
    });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "charger/charger-1/live-telemetry/L1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = getSubmittedPayload();

    expect(payload.strategy).toBe("static_baseline");
    expect(payload.model_type).toBe("pyod_iforest");
    expect(payload.static_baseline_config.training_window_size).toBe(1200);
    expect(payload.static_baseline_config.calibration_window_size).toBe(360);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      betting_function: "power",
      alarm_statistic: "restarted_martingale",
      epsilon: 0.5,
      restarted_ville_threshold: 100,
    });
    expect("adaptive_stream_config" in payload).toBe(false);
    expect("preprocessing_steps" in payload).toBe(false);
  });

  it("submits concrete sensor topics for multivariate alignment", async () => {
    renderMonitoring();

    await screen.findByText(/topic input mode/i);
    await screen.findAllByText("L1");
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = getSubmittedPayload();

    expect(payload.mqtt_topics).toEqual([
      "charger/charger-1/live-telemetry/L1",
      "charger/charger-1/live-telemetry/L2",
      "charger/charger-1/live-telemetry/L3",
    ]);
    expect(payload.performance_config).not.toHaveProperty("alignment_mode");
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
    const payload = getSubmittedPayload();
    expect(payload.static_baseline_config.calibration_window_size).toBe(400);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      betting_function: "power",
      alarm_statistic: "restarted_martingale",
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
    expect(getSubmittedPayload().static_baseline_config.training_window_size).toBe(2000);
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
    expect(getSubmittedPayload().static_baseline_config.model_params.n_estimators).toBe(101);
  });

  it("renders the dynamic lane as a disabled coming-soon preview", async () => {
    renderMonitoring();

    expect(await screen.findByText(/Fixed Ville threshold/i)).toBeTruthy();
    const dynamicLane = screen.getByText("Temporally dependent streams");
    expect(dynamicLane).toBeTruthy();
    expect(
      dynamicLane.closest("[aria-disabled]")?.getAttribute("aria-disabled"),
    ).toBe("true");
    expect(screen.getByText("Coming soon")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /dynamic/i })).toBeNull();
    expect(screen.queryByText(/dynamic model/i)).toBeNull();
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
    expect(getSubmittedPayload().mqtt_topics).toEqual([
      "charger/charger-1/live-telemetry/L2",
      "charger/charger-1/live-telemetry/L3",
    ]);
  });
});
