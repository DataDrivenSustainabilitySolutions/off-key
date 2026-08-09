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
  aberrant_online_isolation_forest: {
    strategy: "adaptive_stream",
    name: "Aberrant Online Isolation Forest",
    parameters: { properties: {} },
  },
  aberrant_x_stream: {
    strategy: "adaptive_stream",
    name: "Aberrant XStream",
    default_parameters: { max_feature_cache_size: 10_000 },
    parameters: {
      properties: {
        max_feature_cache_size: {
          anyOf: [{ type: "integer" }, { type: "null" }],
          default: 10_000,
        },
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
      target: { value: "device/evCharger/charger-1/L1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = getSubmittedPayload();

    expect(payload.strategy).toBe("static_baseline");
    expect(payload.model_type).toBe("pyod_iforest");
    expect(payload.static_baseline_config.training_window_size).toBe(1200);
    expect(payload.static_baseline_config.calibration_window_size).toBe(360);
    expect(payload.static_baseline_config.martingale_config).toEqual({
      automatic_threshold_calibration: {
        false_alarm_probability: 0.01,
        horizon: 1000,
        simulation_count: 5000,
      },
      trackers: [{
        tracker_id: "primary",
        betting_function: "power",
        alarm_statistic: "restarted_martingale",
        epsilon: 0.5,
        threshold_config: { mode: "manual", value: 100 },
      }],
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
      "device/evCharger/charger-1/L1",
      "device/evCharger/charger-1/L2",
      "device/evCharger/charger-1/L3",
    ]);
    expect(payload.performance_config).not.toHaveProperty("alignment_mode");
  });

  it("submits editable epsilon and alarm threshold", async () => {
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
      automatic_threshold_calibration: {
        false_alarm_probability: 0.01,
        horizon: 1000,
        simulation_count: 5000,
      },
      trackers: [{
        tracker_id: "primary",
        betting_function: "power",
        alarm_statistic: "restarted_martingale",
        epsilon: 0.75,
        threshold_config: { mode: "manual", value: 100 },
      }],
    });
  });

  it("defaults CUSUM to an automatically calibrated threshold", async () => {
    renderMonitoring();

    fireEvent.click(
      await screen.findByRole("button", { name: /show advanced settings/i }),
    );
    fireEvent.change(screen.getByLabelText("Alarm statistic"), {
      target: { value: "cusum" },
    });

    expect(
      (screen.getByLabelText("Threshold") as HTMLSelectElement).value,
    ).toBe("automatic");
    expect(screen.getByText("Automatic threshold calibration")).toBeTruthy();
    expect(screen.queryByLabelText("Manual alarm threshold")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());

    expect(
      getSubmittedPayload().static_baseline_config.martingale_config.trackers[0],
    ).toMatchObject({
      alarm_statistic: "cusum",
      threshold_config: { mode: "automatic" },
    });
  });

  it("exposes advanced-setting help on keyboard focus", async () => {
    renderMonitoring();

    expect(
      screen.queryByRole("button", { name: "About Betting method" }),
    ).toBeNull();
    fireEvent.click(
      await screen.findByRole("button", { name: /show advanced settings/i }),
    );
    const helpTrigger = await screen.findByRole("button", {
      name: "About Betting method",
    });

    fireEvent.focus(helpTrigger);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain(
      "Transforms each conformal p-value into a one-step e-value",
    );
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
    const estimatorsInput = (await screen.findAllByDisplayValue("100"))[0];
    if (!estimatorsInput) throw new Error("Expected n_estimators input");
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

  it("switches to the available adaptive lifecycle", async () => {
    renderMonitoring();

    expect(await screen.findByText(/Martingale ensemble/i)).toBeTruthy();
    const dynamicLane = screen.getByRole("button", { name: /Adaptive streams/i });
    expect(dynamicLane.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(dynamicLane);
    expect(await screen.findByText("Adaptive stream lifecycle")).toBeTruthy();
    expect(screen.getByText("Monitor and adapt")).toBeTruthy();
    expect(dynamicLane.getAttribute("aria-pressed")).toBe("true");
  });

  it("submits an explicit None value for nullable adaptive parameters", async () => {
    renderMonitoring();

    fireEvent.click(await screen.findByRole("button", { name: /Adaptive streams/i }));
    fireEvent.change(screen.getByLabelText("Aberrant model"), {
      target: { value: "aberrant_x_stream" },
    });
    const noneControl = screen.getByLabelText("Max Feature Cache Size is None");
    expect((noneControl as HTMLInputElement).checked).toBe(false);
    fireEvent.click(noneControl);
    expect((noneControl as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /start adaptive monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const latestCall = mockPost.mock.calls[mockPost.mock.calls.length - 1];
    const payload = latestCall?.[1] as unknown as {
      model_params: Record<string, unknown>;
      adaptive_stream_config: { model_params: Record<string, unknown> };
    };
    expect(payload.model_params.max_feature_cache_size).toBeNull();
    expect(payload.adaptive_stream_config.model_params.max_feature_cache_size).toBeNull();
  });

  it("disables sensors claimed by an overlapping active service", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/models")) return Promise.resolve(modelCatalog);
      if (url.includes("/monitors/all")) {
        return Promise.resolve([{
          id: 7,
          container_name: "radar-existing",
          mqtt_topics: ["device/evCharger/charger-1/L1"],
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
      "device/evCharger/charger-1/L2",
      "device/evCharger/charger-1/L3",
    ]);
  });
});
