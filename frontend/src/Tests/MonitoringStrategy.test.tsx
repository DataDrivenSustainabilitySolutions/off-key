import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MonitoringServiceCreate } from "@/features/monitoring/MonitoringServiceCreate";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import type { ApiRequestOptions } from "../lib/api-client";
import type { ActiveService, AnomalyDetectionRequest, ModelCapabilities } from "../types/monitoring";

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

vi.mock("../lib/api-client", () => ({
  apiUtils: {
    get: (endpoint: string, options?: ApiRequestOptions) =>
      mockGet(endpoint, options),
    post: (
      endpoint: string,
      payload: AnomalyDetectionRequest,
      options?: ApiRequestOptions
    ) => mockPost(endpoint, payload, options),
  },
}));
const catalogue = { system: { snapshot: null }, telemetry: new SystemLiveTelemetry(), liveStreamIds: [] };
vi.mock("@/features/workspace/catalogue-context", () => ({ useCatalogue: () => catalogue }));

// One entity with three recorded readings, each accepted on its canonical topic.
const target: MonitoringTarget = { id: "charger-1", label: "Site / Charger", inputs: ["L1", "L2", "L3"].map(key => ({
  path: "Site / Charger",
  stream: { id: `stream-${key}`, label: key, topic: `site/charger-1/${key}`, value_type: "number", category: "Power", connection_id: "broker" },
  binding: { entity_id: "charger-1", telemetry_key: key, accepted_topic: `telemetry/charger-1/${key}`, policy: { mode: "sample", interval_seconds: 10 } },
})) };

const vectorCapabilities: ModelCapabilities = {
  event_kind: "tabular",
  feature_count: { minimum: 1, maximum: null },
  score_kind: "non_negative",
  higher_is_more_anomalous: true,
  warmup: { minimum: 20, unit: "events" },
  state: "bounded",
  requires_unit_interval: false,
};

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
  aberrant_rolling_matrix_profile: {
    strategy: "adaptive_stream",
    name: "Aberrant Rolling Matrix Profile",
    algorithm_family: "time_series",
    default_capabilities: {
      ...vectorCapabilities,
      feature_count: { minimum: 1, maximum: 1 },
    },
    parameters: { properties: {} },
  },
  aberrant_half_space_trees: {
    strategy: "adaptive_stream",
    name: "Aberrant Half-Space Trees",
    default_capabilities: { ...vectorCapabilities, requires_unit_interval: true },
    parameters: { properties: {} },
  },
  aberrant_knn: {
    strategy: "adaptive_stream",
    name: "Aberrant KNN",
    default_parameters: {
      similarity_engine: { id: "faiss", params: { window_size: 1000, warm_up: 20 } },
    },
    parameters: {
      properties: {
        similarity_engine: {
          type: "object",
          "x-aberrant-component-kind": "similarity_engine",
          properties: {
            params: {
              type: "object",
              properties: {
                window_size: { type: "integer", minimum: 1 },
                warm_up: { type: "integer", minimum: 1 },
              },
            },
          },
        },
      },
    },
  },
  unavailable_detector: {
    strategy: "adaptive_stream",
    name: "Unavailable detector",
    available: false,
    parameters: { properties: {} },
  },
};

type Setup = { strategy?: "static" | "adaptive"; initialReading?: string; services?: ActiveService[]; byStream?: Map<string, Set<string>> };

/** Open the create form for the entity and wait until its models have loaded. */
async function renderCreate({ strategy = "static", initialReading, services = [], byStream = new Map() }: Setup = {}) {
  render(
    <MemoryRouter>
      <MonitoringServiceCreate targets={[target]} services={services} byStream={byStream} initialTarget="charger-1"
        initialReading={initialReading} collectionReady onStarted={vi.fn(async () => {})} onBack={vi.fn()} />
    </MemoryRouter>
  );
  if (strategy === "static") fireEvent.click(screen.getByRole("button", { name: "Static baseline" }));
  const start = await screen.findByRole("button", { name: strategy === "static" ? /^start monitoring$/i : /start adaptive monitoring/i });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
}

const getSubmittedPayload = (): AnomalyDetectionRequest => {
  const latestCall = mockPost.mock.calls[mockPost.mock.calls.length - 1];
  const payload = latestCall?.[1];
  if (!payload) {
    throw new Error("Expected monitoring request payload");
  }
  return payload;
};

describe("monitoring setup forms", () => {
  beforeEach(() => {
    vi.clearAllMocks(); clearNavigationDrafts();
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/models")) return Promise.resolve(modelCatalog);
      if (url.includes("pipeline-activations")) return Promise.resolve({ phase: "awaiting_heartbeat", service_id: "new-service" });
      return Promise.resolve([]);
    });
    mockPost.mockResolvedValue({ service_id: "new-service", activation_id: "activation" });
  });

  it("submits the static baseline contract", async () => {
    await renderCreate({ initialReading: "stream-L1" });

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = getSubmittedPayload();

    expect(payload.mqtt_topics).toEqual(["telemetry/charger-1/L1"]);
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
    await renderCreate();

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const payload = getSubmittedPayload();

    expect(payload.mqtt_topics).toEqual([
      "telemetry/charger-1/L1",
      "telemetry/charger-1/L2",
      "telemetry/charger-1/L3",
    ]);
    expect(payload.performance_config).not.toHaveProperty("alignment_mode");
  });

  it("submits editable epsilon and alarm threshold", async () => {
    await renderCreate();

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
    await renderCreate();

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
    await renderCreate();

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
    await renderCreate();

    const trainingInput = await screen.findByDisplayValue("1200");
    fireEvent.change(trainingInput, { target: { value: "" } });
    expect((trainingInput as HTMLInputElement).value).toBe("");
  });

  it("blocks below-min training sizes until fixed", async () => {
    await renderCreate();

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
    await renderCreate();

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
    await renderCreate();

    expect(await screen.findByText(/Martingale ensemble/i)).toBeTruthy();
    const dynamicLane = screen.getByRole("button", { name: /Adaptive stream/i });
    expect(dynamicLane.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(dynamicLane);
    expect(await screen.findByRole("heading", { name: "Configure adaptive monitoring" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "About Configure adaptive monitoring" }));
    expect((await screen.findByRole("tooltip")).textContent).toContain("score each point before learning it");
    expect(dynamicLane.getAttribute("aria-pressed")).toBe("true");
  });

  it("submits an explicit None value for nullable adaptive parameters", async () => {
    await renderCreate({ strategy: "adaptive" });

    fireEvent.change(screen.getByLabelText("Model"), {
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

  it("uses catalog families, availability, and feature limits for model selection", async () => {
    await renderCreate({ strategy: "adaptive" });

    const scalarModel = screen.getByRole("option", { name: /Rolling Matrix Profile/ }) as HTMLOptionElement;
    expect(scalarModel.parentElement?.getAttribute("label")).toBe("Time Series");
    expect(scalarModel.disabled).toBe(true);
    expect((screen.getByRole("option", { name: /Unavailable detector/ }) as HTMLOptionElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("checkbox", { name: "L2" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "L3" }));
    expect(scalarModel.disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "aberrant_rolling_matrix_profile" },
    });
    expect(screen.getByText(/Windows count aligned observations/)).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "L2" }));
    fireEvent.click(screen.getByRole("button", { name: /start adaptive monitoring/i }));
    expect(await screen.findByText(/does not support the selected feature count/)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("configures unit-interval scaling and rejects incompatible preprocessing", async () => {
    await renderCreate({ strategy: "adaptive" });

    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "aberrant_half_space_trees" },
    });
    expect((screen.getByLabelText("Scaler") as HTMLSelectElement).value).toBe("min_max_scaler");
    expect((screen.getByLabelText("Range minimum") as HTMLInputElement).value).toBe("0");
    expect((screen.getByLabelText("Range maximum") as HTMLInputElement).value).toBe("1");
    fireEvent.change(screen.getByLabelText("Scaler"), {
      target: { value: "standard_scaler" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start adaptive monitoring/i }));
    expect(await screen.findByText(/requires raw values in \[0, 1\]/)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("validates and submits numeric parameters inside a catalog component", async () => {
    await renderCreate({ strategy: "adaptive" });

    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "aberrant_knn" },
    });
    fireEvent.change(screen.getByLabelText("Warm Up"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: /start adaptive monitoring/i }));
    expect(await screen.findByText("Warm Up must be an integer.")).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Warm Up"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: /start adaptive monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(getSubmittedPayload().model_params.similarity_engine).toEqual({
      id: "faiss", params: { window_size: 1000, warm_up: 30 },
    });
  });

  it("disables sensors claimed by an overlapping active service", async () => {
    const existing: ActiveService = { id: "7", container_id: "workload", container_name: "radar-existing", status: true,
      mqtt_topics: ["telemetry/charger-1/L1"],
      operational_status: { stage: "operational", is_stale: false, message_count: 1, processed_message_count: 1 } };
    await renderCreate({ services: [existing], byStream: new Map([["stream-L1", new Set(["7"])]]) });

    expect(await screen.findByText("Assigned to radar-existing")).toBeTruthy();
    const l1Checkbox = screen.getByText("Assigned to radar-existing").closest("label")?.querySelector("input");
    expect((l1Checkbox as HTMLInputElement | undefined)?.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /start monitoring/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(getSubmittedPayload().mqtt_topics).toEqual([
      "telemetry/charger-1/L2",
      "telemetry/charger-1/L3",
    ]);
  });
});
