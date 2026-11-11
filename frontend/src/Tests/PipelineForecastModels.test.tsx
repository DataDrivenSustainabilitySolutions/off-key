import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pipelinesApi } from "@/features/pipelines/api";
import { normalizeDefinition, normalizeLayout, type PipelineComponent } from "@/features/pipelines/contracts";
import {
  checkpointRows, NO_FORECAST_SERVICE, sizeText, stateText, useForecastModels, withForecastService,
  type ForecastModels,
} from "@/features/pipelines/forecastModels";
import { addBlocker, type GraphDocument } from "@/features/pipelines/model";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { PipelineToolbox } from "@/features/pipelines/PipelineToolbox";
import type { ForecastModelCatalog, ForecastModelInfo } from "@/types/pipelines.generated";

vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: { forecastModels: vi.fn(), downloadForecastModel: vi.fn() },
}));

const CHECKPOINTS = ["mistralai/Timestral-5M", "mistralai/Timestral-28M", "mistralai/Timestral-123M", "mistralai/Timestral-209M"];
const component = (id: string, kind: PipelineComponent["kind"], label: string, fields: PipelineComponent["fields"] = []) => ({
  id, kind, label, description: "", fields, learning: kind === "detector" ? "online" : "none",
  input_type: kind === "source" ? null : "features", output_type: kind === "detector" ? "scores" : "features",
}) as PipelineComponent;
const timestral = {
  ...component("forecast.timestral", "detector", "Timestral forecaster", [
    { name: "checkpoint", label: "Checkpoint", type: "enum", default: CHECKPOINTS[0], has_default: true, options: CHECKPOINTS },
  ]),
  learning: "pretrained", output_type: "forecasts",
} as PipelineComponent;
const components = [
  component("source.aligned", "source", "Input"),
  component("detector:knn", "detector", "Nearest neighbours"),
  timestral,
];
const model = (id: string, change: Partial<ForecastModelInfo> = {}): ForecastModelInfo => ({
  id, family: "timestral", label: `Timestral ${id.split("-").pop()}`, download_bytes: 111_000_000, licence: "Modified MIT",
  levels: [0.5], max_context: 32768, max_horizon: 1024, status: "not_downloaded", ...change,
});
const available = (models: ForecastModelInfo[]): ForecastModelCatalog => ({ service: "available", models });
const mixed = available([
  model(CHECKPOINTS[0]!, { status: "ready", download_bytes: 21_000_000 }),
  model(CHECKPOINTS[1]!),
  model(CHECKPOINTS[2]!, { status: "downloading", progress: 0.43, download_bytes: 490_000_000 }),
  model(CHECKPOINTS[3]!, { status: "failed", error: "ConnectionError: no route to the Hub", download_bytes: 1_837_000_000 }),
]);

const design = (detector = "forecast.timestral", params: object = {}): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "a", label: "Reading A" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "detector", kind: "detector", component: detector, params },
    ] as never,
    edges: [{ source: "input", target: "detector" }] as never,
  }),
  layout: normalizeLayout({}),
});
const forecastState = (catalog?: ForecastModelCatalog, error?: string): ForecastModels =>
  ({ catalog, error, download: vi.fn(), refresh: vi.fn() });
const inspector = (forecast: ForecastModels, document = design(), offered = components) => render(
  <PipelineInspector document={document} catalog={{ catalog_id: "c", authoring_enabled: true, components: offered, templates: [] } as never}
    selected="detector" forecast={forecast} onSelect={vi.fn()} onChange={vi.fn()} />,
);

describe("A deployment without a forecast service", () => {
  const marked = withForecastService(components, { service: "not_deployed" });

  it("marks only the steps that need the service, and only when there is none", () => {
    expect(marked.map((item) => item.unavailable)).toEqual([undefined, undefined, NO_FORECAST_SERVICE]);
    // A service that only does not answer right now, or an answer still on its way, leaves the step on offer.
    expect(withForecastService(components, { service: "unreachable" })).toBe(components);
    expect(withForecastService(components, undefined)).toBe(components);
    expect(withForecastService(components, mixed)).toBe(components);
  });

  it("gives the reason to every way of adding a step", () => {
    const empty = normalizeDefinition({ nodes: [], edges: [] });
    expect(addBlocker(empty, marked[2]!)).toBe(NO_FORECAST_SERVICE);
    expect(addBlocker(empty, marked[1]!)).toBeUndefined();
  });

  it("shows the step in the Add step menu, disabled, with the reason in place of its description", () => {
    render(<PipelineToolbox components={marked} document={{ definition: normalizeDefinition({ nodes: [], edges: [] }), layout: normalizeLayout({}) }}
      onAdd={vi.fn()} />);
    const step = screen.getByRole<HTMLButtonElement>("button", { name: "Add Timestral forecaster" });
    expect(step.disabled).toBe(true);
    expect(step.textContent).toContain(NO_FORECAST_SERVICE);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Add Nearest neighbours" }).disabled).toBe(false);
  });

  it("does not let another detector be changed into it, and says so on a step that already is one", () => {
    const first = inspector(forecastState({ service: "not_deployed" }), design("detector:knn"), marked);
    const option = within(screen.getByRole("combobox", { name: "Detector model" }))
      .getByRole<HTMLOptionElement>("option", { name: "Timestral forecaster (no forecast service)" });
    expect(option.disabled).toBe(true);
    first.unmount();
    inspector(forecastState({ service: "not_deployed" }), design(), marked);
    expect(within(screen.getByRole("group", { name: "Model weights" })).getByRole("status").textContent)
      .toBe("This deployment has no forecast service, which this step needs. A monitor with this step cannot start here.");
    // The step keeps its own model selected, so the design still reads as it was saved.
    expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "Detector model" }).value).toBe("forecast.timestral");
  });
});

describe("The weights of a pretrained forecaster", () => {
  it("lists every checkpoint with its size and state, and marks the one the step uses", () => {
    inspector(forecastState(mixed), design("forecast.timestral", { checkpoint: CHECKPOINTS[1] }));
    const rows = within(screen.getByRole("group", { name: "Model weights" })).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Timestral 5M21 MBReady",
      "Timestral 28M111 MB · used by this stepNot downloadedDownload",
      "Timestral 123M490 MBDownloading, 43%",
      "Timestral 209M1.8 GBDownload failedTry againConnectionError: no route to the Hub",
    ]);
    expect(rows.map((row) => row.className)).toEqual(["", "is-selected", "", ""]);
    expect(within(rows[2]!).getByRole("progressbar", { name: "Download of Timestral 123M" }).getAttribute("value")).toBe("0.43");
    expect(within(rows[0]!).queryByRole("button")).toBeNull();
  });

  it("starts a download, or another try after a failure, for the checkpoint asked for", () => {
    const state = forecastState(mixed);
    inspector(state);
    fireEvent.click(screen.getByRole("button", { name: "Download Timestral 28M" }));
    fireEvent.click(screen.getByRole("button", { name: "Try again to download Timestral 209M" }));
    expect(vi.mocked(state.download).mock.calls).toEqual([[CHECKPOINTS[1]], [CHECKPOINTS[3]]]);
  });

  it("says when a checkpoint is not offered, when the service is silent and when a download did not start", () => {
    expect(checkpointRows(timestral, available([model(CHECKPOINTS[0]!)])).map((row) => [row.label, stateText(row.model)])).toEqual([
      ["Timestral 5M", "Not downloaded"], ["Timestral-28M", "Not offered here"],
      ["Timestral-123M", "Not offered here"], ["Timestral-209M", "Not offered here"],
    ]);
    expect(stateText(model("m", { status: "downloading", progress: null }))).toBe("Downloading");
    expect([sizeText(0), sizeText(21_400_000), sizeText(1_000_000_000)]).toEqual(["", "21 MB", "1 GB"]);
    const silent = forecastState({ service: "unreachable" });
    const { unmount } = inspector(silent);
    expect(screen.getByRole("status").textContent).toContain("The forecast service does not answer right now");
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(silent.refresh).toHaveBeenCalledOnce();
    unmount();
    inspector(forecastState(mixed, "This needs the manage_monitors permission"));
    expect(screen.getByRole("alert").textContent).toBe("The download did not start. This needs the manage_monitors permission");
  });

  it("is left out of steps that hold their own model", () => {
    inspector(forecastState(mixed), design("detector:knn"));
    expect(screen.queryByRole("group", { name: "Model weights" })).toBeNull();
  });
});

describe("Following the forecast service", () => {
  const list = vi.mocked(pipelinesApi.forecastModels);
  const start = vi.mocked(pipelinesApi.downloadForecastModel);
  beforeEach(() => {
    vi.useFakeTimers();
    list.mockReset();
    start.mockReset();
  });
  afterEach(() => vi.useRealTimers());
  const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });

  it("asks nothing where no step needs the service", async () => {
    renderHook(() => useForecastModels(false));
    await settle();
    expect(list).not.toHaveBeenCalled();
  });

  it("asks once while nothing downloads, and keeps asking until a download ends", async () => {
    const waiting = available([model(CHECKPOINTS[0]!)]);
    const running = available([model(CHECKPOINTS[0]!, { status: "downloading", progress: 0.5 })]);
    const done = available([model(CHECKPOINTS[0]!, { status: "ready" })]);
    list.mockResolvedValueOnce(waiting).mockResolvedValueOnce(running).mockResolvedValueOnce(running).mockResolvedValue(done);
    start.mockResolvedValue(running.models![0]!);
    const { result } = renderHook(() => useForecastModels(true));
    await settle();
    expect(result.current.catalog).toEqual(waiting);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(list).toHaveBeenCalledTimes(1);

    act(() => result.current.download(CHECKPOINTS[0]!));
    await settle();
    expect(start).toHaveBeenCalledWith(CHECKPOINTS[0]);
    expect(result.current.catalog?.models?.[0]?.status).toBe("downloading");
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.catalog).toEqual(done);
    const asked = list.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(list).toHaveBeenCalledTimes(asked);
  });

  it("reports why a download did not start or the state could not be read, and can ask again", async () => {
    const waiting = available([model(CHECKPOINTS[0]!)]);
    list.mockResolvedValue(waiting);
    start.mockRejectedValue(new Error("This needs the manage_monitors permission"));
    const { result } = renderHook(() => useForecastModels(true));
    await settle();
    act(() => result.current.download(CHECKPOINTS[0]!));
    await settle();
    expect(result.current.error).toBe("This needs the manage_monitors permission");
    expect(result.current.catalog).toEqual(waiting);

    list.mockRejectedValueOnce(new Error("Network Error"));
    act(() => result.current.refresh());
    await settle();
    expect(result.current).toMatchObject({ catalog: undefined, error: "Network Error" });
    act(() => result.current.refresh());
    await settle();
    expect(result.current).toMatchObject({ catalog: waiting, error: undefined });
  });
});
