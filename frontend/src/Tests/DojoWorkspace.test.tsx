import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DojoWorkspace } from "@/features/dojo/DojoWorkspace";
import { dojoApi } from "@/features/dojo/api";
import { pipelinesApi } from "@/features/pipelines/api";
import type { Comparison, DatasetView, LabelView, MethodMetrics, RunMetrics, RunSummary } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import { fromLocalInput, toLocalInput } from "@/features/dojo/model";

const access = vi.hoisted(() => ({ allowed: true, monitors: false, guest: false }));
const selectSource = vi.hoisted(() => vi.fn());
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: !access.guest, isGuest: access.guest,
  can: (permission: string) => !access.guest && access.allowed && (permission === "use_dojo" || access.monitors && permission === "manage_monitors") }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/features/charts/EChart", () => ({
  EChart: ({ accessibleDescription, onViewportChange }: { accessibleDescription: string; onViewportChange?: (a: number, b: number) => void }) =>
    <div role="img" aria-label={accessibleDescription}>
      {onViewportChange && <button type="button" onClick={() => onViewportChange(Date.parse("2024-01-01T00:10:00Z"),
        Date.parse("2024-01-01T00:20:00Z"))}>Zoom chart</button>}
    </div>,
}));
vi.mock("@/features/workspace/catalogue-context", () => ({
  useCatalogue: () => ({
    selected: { key: "pump", kind: "device", entityKind: "device", label: "Pump 1", streamIds: ["r1", "r2", "r3"] },
    streamIds: ["r1", "r2", "r3"],
    selectSource,
    document: { readings: [
      { id: "r1", label: "Voltage", unit: "V", value_type: "number", device_id: "pump-1", broker_id: "b" },
      { id: "r2", label: "Current", unit: "A", value_type: "number", device_id: "pump-1", broker_id: "b" },
      { id: "r3", label: "Mode", value_type: "text", device_id: "pump-1", broker_id: "b" },
    ] },
  }),
}));
vi.mock("@/features/dojo/api", () => ({ dojoApi: {
  datasets: vi.fn(), dataset: vi.fn(), importCsv: vi.fn(), importHistory: vi.fn(), benchmarks: vi.fn(), importBenchmarks: vi.fn(), changeDataset: vi.fn(), deleteDataset: vi.fn(),
  points: vi.fn(), labels: vi.fn(), labelSuggestions: vi.fn(), createLabel: vi.fn(), createLabels: vi.fn(), changeLabel: vi.fn(), deleteLabel: vi.fn(), runs: vi.fn(), run: vi.fn(),
  pendingLabels: vi.fn(), proposeLabelsByRule: vi.fn(), acceptPendingLabels: vi.fn(), dismissPendingLabels: vi.fn(),
  createRun: vi.fn(), cancelRun: vi.fn(), deleteRun: vi.fn(), promoteRun: vi.fn(), results: vi.fn(), metrics: vi.fn(), compare: vi.fn(),
  calibration: vi.fn(), suites: vi.fn(),
} }));
vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { catalog: vi.fn(), list: vi.fn(), get: vi.fn() } }));

const T0 = "2024-01-01T00:00:00Z";
const dataset: DatasetView = {
  id: "d1", name: "Pump trips", description: "", origin: "history", point_count: 240, series_count: 2,
  start_at: T0, end_at: "2024-01-01T02:00:00Z", created_by: 1, created_at: T0, source: {},
  series: [
    { id: "s1", position: 0, name: "Voltage", unit: "V", reading_id: "r1", point_count: 120, start_at: T0, end_at: T0 },
    { id: "s2", position: 1, name: "Current", unit: "A", reading_id: "r2", point_count: 120, start_at: T0, end_at: T0 },
  ],
};
const label: LabelView = { id: "l1", dataset_id: "d1", start_at: "2024-01-01T00:30:00Z", end_at: "2024-01-01T00:40:00Z",
  note: "Bearing", created_by: 1, created_at: T0 };
const run = (id: string, name: string, status: RunSummary["status"] = "succeeded"): RunSummary => ({
  id, dataset_id: "d1", name, status, strategy: "adaptive_stream", points_total: 240, points_read: 240, result_count: 120,
  alarm_count: 3, error: null, created_by: 1, created_at: T0, started_at: T0, finished_at: T0 });
const metrics = (runId: string, name: string, detected: number, falseAlarms: number): RunMetrics => ({
  run_id: runId, run_name: name, strategy: "adaptive_stream", scored_from: T0, scored_to: "2024-01-01T02:00:00Z",
  labels_total: 1, labels_scored: 1, labels_detected: detected, detection_rate: detected, median_delay_seconds: detected ? 120 : null,
  max_delay_seconds: detected ? 120 : null, alarm_count: 3, false_alarms: falseAlarms, evaluated_seconds: 6600,
  false_alarms_per_day: falseAlarms * 86400 / 6600,
  scores: { scored_results: 110, labelled_results: 10, pr_auc: detected ? 0.42 : 0.091, auroc: detected ? 0.88 : 0.5,
    vus_pr: detected ? 0.5 : 0.1, top_score_at: T0, top1_hit: detected > 0,
    score_autocorrelation: detected ? 0.1 : 0.93 },
  diagnostics: { results: 120, scored_share: 0.92, warm_up_seconds: 600, alarm_share: 0.03, alarm_episodes: 3,
    episodes_per_day: 36, longest_episode_seconds: 120, episodes_after_gaps: 0, after_gap_share: 0,
    score_trend: detected ? 0.05 : 0.81, commonest_score_share: 0.01,
    quick_returns: detected ? 0 : 1, alarms_alone: detected ? 0 : 2,
    follows: detected ? [] : [{ series: "Speed", correlation: 0.9 }],
    findings: detected ? [] : ["The scores rank with the value of Speed (0.90)."] },
  labels: [{ label_id: "l1", start_at: label.start_at, end_at: label.end_at, outcome: detected ? "detected" : "missed",
    first_alarm_at: detected ? "2024-01-01T00:32:00Z" : null, delay_seconds: detected ? 120 : null }] });

function mount(path: string) {
  const router = createMemoryRouter([{ path: "/dojo", element: <DojoWorkspace /> }, { path: "/", element: <p>Monitoring</p> }],
    { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  vi.clearAllMocks();
  access.allowed = true;
  access.monitors = false;
  access.guest = false;
  vi.mocked(dojoApi.datasets).mockResolvedValue({ items: [dataset], next_offset: null });
  vi.mocked(dojoApi.suites).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(dojoApi.dataset).mockResolvedValue(dataset);
  vi.mocked(dojoApi.labels).mockResolvedValue({ items: [label] });
  vi.mocked(dojoApi.labelSuggestions).mockResolvedValue({ items: [], truncated: false });
  vi.mocked(dojoApi.pendingLabels).mockResolvedValue({ items: [] });
  vi.mocked(dojoApi.points).mockResolvedValue({ items: [{ timestamp: T0, value: 1 }], next_after: null });
  vi.mocked(dojoApi.runs).mockResolvedValue({ items: [run("r1", "Forest"), run("r2", "Baseline")], next_offset: null });
  vi.mocked(dojoApi.results).mockResolvedValue({ items: [], next_after: null });
});

describe("Dojo workspace", () => {
  it("lets public visitors inspect datasets and labels without mutation controls", async () => {
    access.guest = true;
    mount("/dojo?dataset=d1");
    expect(await screen.findByRole("heading", { name: "Pump trips" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Rename dataset" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add label" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete label" })).toBeNull();
    expect(screen.getByText("Bearing")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.queryByRole("button", { name: "New run" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
  it("opens a run linked on its own, such as a proposal's test, among its dataset's runs", async () => {
    vi.mocked(dojoApi.run).mockResolvedValue({ ...run("r2", "Baseline"), definition: {} } as never);
    const router = mount("/dojo?run=r2");
    const row = (await screen.findByText("Baseline")).closest("tr")!;
    expect(row.getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Forest").closest("tr")!.getAttribute("aria-current")).toBeNull();
    expect(dojoApi.run).toHaveBeenCalledWith("r2", expect.anything());
    expect(router.state.location.search).toBe("?dataset=d1&tab=runs&run=r2");
  });

  it("says when a linked run cannot be opened", async () => {
    vi.mocked(dojoApi.run).mockRejectedValue(new Error("Run not found"));
    mount("/dojo?run=gone");
    expect(await screen.findByRole("heading", { name: "The run could not be opened" })).toBeTruthy();
    expect(screen.getByText("Run not found")).toBeTruthy();
  });

  it("names a directly opened dataset, its sections, and the list on return", async () => {
    vi.mocked(dojoApi.compare).mockResolvedValue({ dataset_id: "d1", labels: [label],
      runs: [metrics("r1", "Forest", 1, 0), metrics("r2", "Baseline", 0, 0)] });
    mount("/dojo?dataset=d1&tab=runs");
    await screen.findByRole("heading", { name: "Pump trips", level: 1 });
    expect(document.title).toBe("Pump trips — Runs · Dojo · Aberration");
    fireEvent.click(screen.getByRole("tab", { name: "Compare" }));
    expect(document.title).toBe("Pump trips — Compare · Dojo · Aberration");
    fireEvent.click(screen.getByRole("tab", { name: "Values and labels" }));
    expect(document.title).toBe("Pump trips · Dojo · Aberration");
    fireEvent.click(screen.getByRole("link", { name: "All datasets" }));
    await screen.findByRole("link", { name: "Pump trips" });
    expect(document.title).toBe("Datasets · Dojo · Aberration");
  });

  it("names denied dataset links without leaving an unrelated page title", () => {
    access.allowed = false;
    mount("/dojo?dataset=d1");
    expect(document.title).toBe("Access denied · Dojo · Aberration");
    expect(dojoApi.dataset).not.toHaveBeenCalled();
  });

  it("loads older runs without dropping the runs already shown", async () => {
    vi.mocked(dojoApi.runs).mockImplementation(async query => query?.offset === 100
      ? { items: [run("older", "Older run")], next_offset: null }
      : { items: [run("newer", "Newer run")], next_offset: 100 });
    mount("/dojo?dataset=d1&tab=runs");
    await screen.findByText("Newer run");
    fireEvent.click(await screen.findByRole("button", { name: "Load more runs" }));
    await screen.findByText("Older run");
    expect(screen.getByText("Newer run")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Load more runs" })).toBeNull();
  });

  it("loads designs beyond the first page", async () => {
    vi.mocked(pipelinesApi.catalog).mockResolvedValue({ templates: [] } as never);
    vi.mocked(pipelinesApi.list).mockImplementation(async query => (query?.offset === 100
      ? { items: [{ id: "older", name: "Older design" }], next_offset: null }
      : { items: [{ id: "newer", name: "Newer design" }], next_offset: 100 }) as never);
    mount("/dojo?dataset=d1&tab=runs");
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    await screen.findByRole("option", { name: "Newer design" });
    fireEvent.click(await screen.findByRole("button", { name: "Load more designs" }));
    await screen.findByRole("option", { name: "Older design" });
    expect(screen.getByRole("option", { name: "Newer design" })).toBeTruthy();
  });

  it("ignores a superseded design response even when it arrives last", async () => {
    vi.mocked(pipelinesApi.catalog).mockResolvedValue({ templates: [] } as never);
    vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [{ id: "a", name: "A" }, { id: "b", name: "B" }], next_offset: null } as never);
    const design = (id: string) => ({ strategy: "adaptive_stream", input_slots: [{ id: "value", label: "Voltage" }], nodes: [{ id }], edges: [], settings: {} });
    const a = design("a"), b = design("b");
    let resolveA!: (value: unknown) => void;
    let resolveB!: (value: unknown) => void;
    vi.mocked(pipelinesApi.get).mockImplementation(id => new Promise(resolve => {
      if (id === "a") resolveA = resolve; else resolveB = resolve;
    }) as never);
    vi.mocked(dojoApi.createRun).mockResolvedValue({} as never);
    mount("/dojo?dataset=d1&tab=runs");
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    await screen.findByRole("option", { name: "A" });
    const chooser = screen.getByLabelText("Design");
    fireEvent.change(chooser, { target: { value: "design:a" } });
    fireEvent.change(chooser, { target: { value: "design:b" } });
    await act(async () => { resolveB({ draft: b }); });
    await act(async () => { resolveA({ draft: a }); });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(dojoApi.createRun).toHaveBeenCalledWith(expect.objectContaining({ definition: b, name: "B" })));
  });

  it("shows the catalogue selection with a link to its readings page and a way to clear it", async () => {
    mount("/dojo");
    const scope = await screen.findByLabelText("Selected source");
    within(scope).getByText("Pump 1");
    expect(within(scope).getByRole("link", { name: "Device readings" }).getAttribute("href")).toBe("/details/pump-1?source=pump");
    fireEvent.click(within(scope).getByRole("button", { name: "Show all sources" }));
    expect(selectSource).toHaveBeenCalledWith(null);
  });

  it("lists datasets and copies the selected entity's numeric readings", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue({ ...dataset, id: "d2", name: "Pump 1" });
    const router = mount("/dojo");
    expect((await screen.findByRole("link", { name: "Pump trips" })).getAttribute("href")).toBe("/dojo?dataset=d1");
    fireEvent.click(screen.getByRole("button", { name: "Copy recorded readings" }));
    const dialog = await screen.findByRole("dialog", { name: "Copy recorded readings" });
    expect(within(dialog).queryByText("Mode")).toBeNull();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Current/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(dojoApi.importHistory).toHaveBeenCalledWith(expect.objectContaining({ name: "Pump 1", reading_ids: ["r1"] })));
    await waitFor(() => expect(router.state.location.search).toBe("?dataset=d2"));
  });

  it("searches a benchmark collection and opens the one series it imports", async () => {
    const series = (number: number, name: string, extra = {}) => ({ id: `ucr-${number}`, collection: "ucr-anomaly-2021", number, name,
      domain: "ECG", variant: "original" as const, points: 11000, train_points: 2500, anomaly_first: 5400, anomaly_last: 5599, ...extra });
    vi.mocked(dojoApi.benchmarks).mockResolvedValue({
      collections: [{ id: "ucr-anomaly-2021", name: "UCR Time Series Anomaly Archive", description: "250 series.", authors: "R. Wu and E. Keogh",
        citation: "Wu and Keogh, TKDE 2021", url: "https://example.org/ucr", license: "No stated licence.", series_count: 250, domains: ["ECG", "Power demand"] }],
      items: [series(112, "BIDMC1"), series(120, "ECG2", { dataset_id: "d9" })], total: 2, next_offset: null,
    });
    vi.mocked(dojoApi.importBenchmarks).mockResolvedValue({ items: [{ ...dataset, id: "d3", origin: "benchmark", series_count: 1 }], imported: 1 });
    vi.mocked(dojoApi.dataset).mockResolvedValue({ ...dataset, id: "d3" });
    const router = mount("/dojo?view=benchmarks");
    fireEvent.click(await screen.findByRole("button", { name: "Add public series" }));
    const dialog = await screen.findByRole("dialog", { name: "Add public series" });
    expect(await within(dialog).findByText(/Cite: Wu and Keogh, TKDE 2021/)).toBeTruthy();
    expect(within(dialog).getByText("Imported")).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Domain" }), { target: { value: "ECG" } });
    await waitFor(() => expect(dojoApi.benchmarks).toHaveBeenLastCalledWith(
      expect.objectContaining({ domain: "ECG", variant: "original" }), expect.anything()));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /112 · BIDMC1/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Import series" }));
    await waitFor(() => expect(dojoApi.importBenchmarks).toHaveBeenCalledWith({ series_ids: ["ucr-112"] }));
    await waitFor(() => expect(router.state.location.search).toBe("?view=benchmarks&dataset=d3"));
  });

  it("copies everything stored by default and a chosen window on request", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue({ ...dataset, id: "d2", name: "Pump 1" });
    const copy = async (choose: (dialog: HTMLElement) => void) => {
      cleanup();
      const router = mount("/dojo");
      fireEvent.click(await screen.findByRole("button", { name: "Copy recorded readings" }));
      const dialog = await screen.findByRole("dialog", { name: "Copy recorded readings" });
      expect((within(dialog).getByRole("radio", { name: "Everything stored" }) as HTMLInputElement).checked).toBe(true);
      choose(dialog);
      const calls = vi.mocked(dojoApi.importHistory).mock.calls.length;
      fireEvent.click(within(dialog).getByRole("button", { name: "Copy" }));
      await waitFor(() => expect(dojoApi.importHistory).toHaveBeenCalledTimes(calls + 1));
      router.dispose();
      return vi.mocked(dojoApi.importHistory).mock.calls[calls]![0];
    };
    const before = Date.now();
    const everything = await copy(dialog => expect(within(dialog).queryByLabelText("From")).toBeNull());
    expect(everything.start).toBeUndefined();
    expect(Date.parse(everything.end)).toBeGreaterThanOrEqual(before);

    const day = await copy(dialog => fireEvent.click(within(dialog).getByRole("radio", { name: "Last 24 hours" })));
    expect(Date.parse(day.end) - Date.parse(day.start!)).toBe(86_400_000 + 1000);

    const custom = await copy(dialog => {
      fireEvent.click(within(dialog).getByRole("radio", { name: "Custom" }));
      fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "2024-01-01T00:00:00" } });
      fireEvent.change(within(dialog).getByLabelText("To"), { target: { value: "2024-01-02T00:00:00" } });
    });
    expect(custom).toMatchObject({ start: new Date("2024-01-01T00:00:00").toISOString(),
      end: new Date("2024-01-02T00:00:00").toISOString() });
  });

  it("marks the zoomed range of the chart as a label", async () => {
    vi.mocked(dojoApi.createLabel).mockResolvedValue({ ...label, id: "l2" });
    mount("/dojo?dataset=d1");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toContain("Pump trips");
    fireEvent.click(await screen.findByRole("button", { name: "Zoom chart" }));
    fireEvent.click(screen.getByRole("button", { name: "Use the zoomed range" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Note/ }), { target: { value: " Seal leak " } });
    fireEvent.click(screen.getByRole("button", { name: "Add label" }));
    await waitFor(() => expect(dojoApi.createLabel).toHaveBeenCalledWith("d1",
      { start_at: "2024-01-01T00:10:00.000Z", end_at: "2024-01-01T00:20:00.000Z", note: "Seal leak" }));
    expect(dojoApi.labels).toHaveBeenCalledTimes(2);
    expect((screen.getByRole("textbox", { name: "Label note" }) as HTMLInputElement).value).toBe("Bearing");
  });

  it("offers recorded alarms that no label covers yet as labels", async () => {
    const suggestion = (start: string, end: string, count: number, monitors = ["m1"]) => ({
      start_at: `2024-01-01T${start}Z`, end_at: `2024-01-01T${end}Z`, alarm_count: count, monitor_ids: monitors, reading_ids: ["r1"] });
    vi.mocked(dojoApi.labelSuggestions).mockResolvedValue({ truncated: false, items: [
      suggestion("00:05:00", "00:09:00", 3, ["m1", "m2"]),
      suggestion("00:35:00", "00:36:00", 2),
      suggestion("01:10:00", "01:10:01", 1),
    ] });
    vi.mocked(dojoApi.createLabels).mockResolvedValue({ items: [] });
    mount("/dojo?dataset=d1");
    const list = await screen.findByRole("list", { name: "Suggested labels" });
    expect(dojoApi.labelSuggestions).toHaveBeenCalledWith("d1", {}, expect.any(AbortSignal));
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    within(items[0]!).getByText("3 recorded alarms from 2 monitors");
    screen.getByText("One more overlaps a label already.");

    fireEvent.click(within(items[0]!).getByRole("button", { name: "Adjust" }));
    expect(fromLocalInput((screen.getByLabelText("From") as HTMLInputElement).value)).toBe("2024-01-01T00:05:00.000Z");
    expect(fromLocalInput((screen.getByLabelText("To") as HTMLInputElement).value)).toBe("2024-01-01T00:09:00.000Z");
    expect((screen.getByRole("textbox", { name: /Note/ }) as HTMLInputElement).value).toBe("3 recorded alarms");

    fireEvent.click(within(items[1]!).getByRole("button", { name: "Add as label" }));
    await waitFor(() => expect(dojoApi.createLabels).toHaveBeenCalledWith("d1", { labels: [
      { start_at: "2024-01-01T01:10:00Z", end_at: "2024-01-01T01:10:01Z", note: "Recorded alarm" }] }));
    expect(dojoApi.labels).toHaveBeenCalledTimes(2);

    const addAll = screen.getByRole("button", { name: "Add all as labels" }) as HTMLButtonElement;
    await waitFor(() => expect(addAll.disabled).toBe(false));
    fireEvent.click(addAll);
    // One write for all of them, so a long list stays within the write rate limit.
    await waitFor(() => expect(dojoApi.createLabels).toHaveBeenLastCalledWith("d1", { labels: [
      { start_at: "2024-01-01T00:05:00Z", end_at: "2024-01-01T00:09:00Z", note: "3 recorded alarms" },
      { start_at: "2024-01-01T01:10:00Z", end_at: "2024-01-01T01:10:01Z", note: "Recorded alarm" },
    ] }));
    expect(dojoApi.createLabels).toHaveBeenCalledTimes(2);
    expect(dojoApi.createLabel).not.toHaveBeenCalled();
  });

  it("labels by a rule and lets a member add, adjust or dismiss what members and agents proposed", async () => {
    const proposed = (id: string, start: string, end: string, agent: string | null) => ({
      id, dataset_id: "d1", start_at: `2024-01-01T${start}Z`, end_at: `2024-01-01T${end}Z`, note: agent ? "Hot" : "",
      rule: "Voltage > 230", created_by: agent ? null : 1, created_by_agent: agent, created_at: T0 });
    const waiting = [
      proposed("p1", "00:05:00", "00:09:00", "Labeller"),
      // On the label already, so it cannot be added.
      proposed("p2", "00:35:00", "00:36:00", null),
      proposed("p3", "01:10:00", "01:12:00", null),
    ];
    vi.mocked(dojoApi.pendingLabels).mockResolvedValue({ items: waiting });
    vi.mocked(dojoApi.proposeLabelsByRule).mockResolvedValue({ items: [waiting[2]!], skipped: 1, truncated: false, replaced: 0 });
    vi.mocked(dojoApi.acceptPendingLabels).mockResolvedValue({ items: [] });
    vi.mocked(dojoApi.dismissPendingLabels).mockResolvedValue(undefined);
    mount("/dojo?dataset=d1");
    const list = await screen.findByRole("list", { name: "Pending labels" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    within(items[0]!).getByText(/Hot · by Labeller/);
    within(items[1]!).getByText(/by you/);
    screen.getByText("Series: Voltage, Current. Combine comparisons with and, or and not, as in a Gate step. Each series keeps its last value until its next one.");

    fireEvent.change(screen.getByRole("textbox", { name: "Condition" }), { target: { value: "Voltage > 230" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "At least (min)" }), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Find intervals" }));
    await waitFor(() => expect(dojoApi.proposeLabelsByRule).toHaveBeenCalledWith("d1",
      { condition: "Voltage > 230", note: "", min_duration_seconds: 120, merge_gap_seconds: 0 }));
    expect(await screen.findByText("One interval found, 1 more on a label already.")).toBeTruthy();

    fireEvent.click(within(items[0]!).getByRole("button", { name: "Add as label" }));
    await waitFor(() => expect(dojoApi.acceptPendingLabels).toHaveBeenCalledWith("d1", { items: [{ id: "p1" }] }));

    fireEvent.click(within(items[1]!).getByRole("button", { name: "Adjust" }));
    expect(fromLocalInput((screen.getByLabelText("From") as HTMLInputElement).value)).toBe("2024-01-01T01:10:00.000Z");
    fireEvent.change(screen.getByLabelText("To"), { target: { value: toLocalInput("2024-01-01T01:15:00Z") } });
    fireEvent.click(screen.getByRole("button", { name: "Add proposed label" }));
    await waitFor(() => expect(dojoApi.acceptPendingLabels).toHaveBeenLastCalledWith("d1", { items: [
      { id: "p3", start_at: "2024-01-01T01:10:00.000Z", end_at: "2024-01-01T01:15:00.000Z", note: "" }] }));
    expect(dojoApi.createLabel).not.toHaveBeenCalled();

    const dismissAll = screen.getByRole("button", { name: "Dismiss all" }) as HTMLButtonElement;
    await waitFor(() => expect(dismissAll.disabled).toBe(false));
    fireEvent.click(dismissAll);
    await waitFor(() => expect(dojoApi.dismissPendingLabels).toHaveBeenCalledWith("d1", { ids: ["p1", "p2", "p3"] }));
  });

  it("looks for no recorded alarms on an uploaded dataset", async () => {
    vi.mocked(dojoApi.dataset).mockResolvedValue({ ...dataset, origin: "csv",
      series: dataset.series.map(item => ({ ...item, reading_id: null })) });
    mount("/dojo?dataset=d1");
    await screen.findByRole("button", { name: "Use the zoomed range" });
    expect(screen.queryByRole("region", { name: "Recorded alarms" })).toBeNull();
    expect(dojoApi.labelSuggestions).not.toHaveBeenCalled();
  });

  it("binds a template's inputs to the dataset's series and queues a run", async () => {
    vi.mocked(pipelinesApi.catalog).mockResolvedValue({ templates: [{ id: "t1", name: "Isolation forest", layout: { nodes: {} },
      definition: { strategy: "adaptive_stream", input_slots: [{ id: "current", label: "Current", unit: "A" }, { id: "voltage", label: "Line", unit: "V" }],
        nodes: [], edges: [], settings: {} } }] } as never);
    vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [], next_offset: null });
    vi.mocked(dojoApi.createRun).mockResolvedValue({} as never);
    mount("/dojo?dataset=d1&tab=runs");
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    const dialog = await screen.findByRole("dialog", { name: "New run" });
    await within(dialog).findByRole("option", { name: "Isolation forest" });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Design" }), { target: { value: "template:t1" } });
    expect((await within(dialog).findByRole("combobox", { name: "Series for Current" }) as HTMLSelectElement).value).toBe("s2");
    expect((within(dialog).getByRole("combobox", { name: "Series for Line" }) as HTMLSelectElement).value).toBe("s1");
    fireEvent.click(within(dialog).getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(dojoApi.createRun).toHaveBeenCalledWith(expect.objectContaining({
      dataset_id: "d1", name: "Isolation forest", bindings: { current: "s2", voltage: "s1" },
      alignment: { hold_intervals: 3, minimum_hold_seconds: 30 } })));
  });

  it("asks for a comparison of calibration methods only where a design has a score boundary", async () => {
    const design = (id: string, name: string, policy: string) => ({ id, name, layout: { nodes: {} }, definition: {
      schema_version: 2, input_slots: [{ id: "current", label: "Current", unit: "A" }], edges: [], settings: {},
      nodes: [{ id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
        { id: "policy", kind: "policy", component: policy }] } });
    vi.mocked(pipelinesApi.catalog).mockResolvedValue({ templates: [design("t1", "Threshold", "policy.quantile"),
      design("t2", "Martingale", "policy.martingale")] } as never);
    vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [], next_offset: null });
    vi.mocked(dojoApi.createRun).mockResolvedValue({} as never);
    mount("/dojo?dataset=d1&tab=runs");
    fireEvent.click(await screen.findByRole("button", { name: "New run" }));
    const dialog = await screen.findByRole("dialog", { name: "New run" });
    await within(dialog).findByRole("option", { name: "Martingale" });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Design" }), { target: { value: "template:t2" } });
    const refused = await within(dialog).findByRole("checkbox", { name: "Compare calibration methods" }) as HTMLInputElement;
    expect(refused.disabled).toBe(true);
    within(dialog).getByText(/alarms on a conformal martingale/);
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Design" }), { target: { value: "template:t1" } });
    await within(dialog).findByText(/The run takes longer/);
    const offered = within(dialog).getByRole("checkbox", { name: "Compare calibration methods" }) as HTMLInputElement;
    expect(offered.disabled).toBe(false);
    fireEvent.click(offered);
    fireEvent.click(within(dialog).getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(dojoApi.createRun).toHaveBeenCalledWith(expect.objectContaining({
      name: "Threshold", compare_calibration: true })));
  });

  it("ranks the calibration methods a run also tried", async () => {
    vi.mocked(dojoApi.runs).mockResolvedValue({ items: [{ ...run("r1", "Forest"), compares_calibration: true },
      run("r2", "Baseline")], next_offset: null });
    vi.mocked(dojoApi.compare).mockResolvedValue({ dataset_id: "d1", labels: [label],
      runs: [metrics("r1", "Forest", 1, 2), metrics("r2", "Baseline", 0, 0)] });
    const method = (id: string, name: string, family: MethodMetrics["family"], detected: number, perDay: number,
      extra: Partial<MethodMetrics> = {}): MethodMetrics => ({ method: id, name, family, own: false, failed: null,
      alarm_count: 4, alarm_share: 0.0125, labels_scored: 2, labels_detected: detected, detection_rate: detected / 2,
      median_delay_seconds: 120, false_alarms: perDay, false_alarms_per_day: perDay, ...extra });
    vi.mocked(dojoApi.calibration).mockResolvedValue({ run_id: "r1", run_name: "Forest", alpha: 0.01, consecutive: 2,
      results: 320, scored_from: T0, scored_to: "2024-01-01T02:00:00Z", labels_total: 2, evaluated_seconds: 6000,
      methods: [method("fixed_split", "Fixed split", "fixed", 1, 3, { own: true }), method("aci", "ACI", "conformal", 2, 5),
        method("pid", "Conformal PID", "conformal", 2, 1), method("nig", "Discounted Bayes", "bayesian", 2, 0,
          { failed: "ArithmeticError: no boundary", alarm_share: null, detection_rate: null,
            false_alarms_per_day: null })] });
    mount("/dojo?dataset=d1&tab=compare");
    const table = await screen.findByRole("table", { name: "Calibration methods" });
    expect(dojoApi.calibration).toHaveBeenCalledWith("r1", expect.any(AbortSignal));
    // Most labels detected first, then fewest false alarms per day; a method that stopped goes last.
    expect(within(table).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell")[0]!.textContent)).toEqual([
      "Conformal PIDConformal", "ACIConformal", "Fixed splitThis runFixed",
      "Discounted BayesBayesian · stopped early: ArithmeticError: no boundary"]);
    // It shows what it found before it stopped, without a rate over results it never judged.
    const stopped = within(table).getByRole("row", { name: /Discounted Bayes/ });
    expect(within(stopped).getAllByRole("cell").slice(1, 3).map(cell => cell.textContent)).toEqual(["2", "–"]);
    const best = within(table).getByRole("row", { name: /Conformal PID/ });
    expect(within(best).getAllByRole("cell")[5]!.className).toBe("dj-metric-best");
    within(best).getByText("1.3 %");
    screen.getByText(/every method judged the same 320 results/);
    screen.getByText(/alarm rate of 1 % and alarming after 2 scores in a row/);
  });

  it("says how to get a comparison of calibration methods when no run has one", async () => {
    vi.mocked(dojoApi.compare).mockResolvedValue({ dataset_id: "d1", labels: [label],
      runs: [metrics("r1", "Forest", 1, 2), metrics("r2", "Baseline", 0, 0)] });
    mount("/dojo?dataset=d1&tab=compare");
    await screen.findByText(/No finished run has compared calibration methods yet/);
    expect(dojoApi.calibration).not.toHaveBeenCalled();
  });

  it("compares finished runs and marks the better one", async () => {
    vi.mocked(dojoApi.runs).mockResolvedValue({ items: [run("r1", "Forest"), run("r2", "Baseline"), run("r3", "Waiting", "queued")],
      next_offset: null });
    const comparison: Comparison = { dataset_id: "d1", labels: [label],
      runs: [metrics("r1", "Forest", 1, 2), metrics("r2", "Baseline", 0, 0)] };
    vi.mocked(dojoApi.compare).mockResolvedValue(comparison);
    mount("/dojo?dataset=d1&tab=compare");
    const table = await screen.findByRole("table", { name: "Run metrics" });
    expect(dojoApi.compare).toHaveBeenCalledWith("d1", ["r1", "r2"], expect.any(AbortSignal));
    expect(screen.queryByRole("checkbox", { name: "Waiting" })).toBeNull();
    const detected = within(table).getByRole("row", { name: /Labels detected/ });
    expect(within(detected).getByText("1 of 1").className).toBe("dj-metric-best");
    const falseAlarms = within(table).getByRole("row", { name: /^False alarms 2 0$/ });
    expect(within(falseAlarms).getByText("0").className).toBe("dj-metric-best");
    const outcomes = screen.getByRole("table", { name: "Label outcomes" });
    within(outcomes).getByText("Detected");
    within(outcomes).getByText("after 2 min");
    within(outcomes).getByText("Missed");
    expect(dojoApi.results).toHaveBeenCalledWith("r1", expect.objectContaining({ alarm: true }), expect.any(AbortSignal));
    // The scores are judged before any threshold too.
    const prAuc = within(table).getByRole("row", { name: /^PR-AUC/ });
    expect(within(prAuc).getByText("0.420").className).toBe("dj-metric-best");
    within(table).getByRole("row", { name: /^Top score at the label Yes No$/ });
    within(table).getByRole("row", { name: /^Score persistence \(20 back\) 0.10 0.93 · follows the level$/ });
    // And without labels.
    within(table).getByRole("row", { name: /^Score trend over the run 0.05 0.81$/ });
    within(table).getByRole("row", { name: /^Scores follow an input – Speed 0.90$/ });
    within(table).getByRole("row", { name: /^Alarms back within 10 values 0 % 100 % · flaps$/ });
    within(table).getByRole("row", { name: /^Alarms no other run raised 0 2$/ });
    const found = screen.getByRole("list", { name: "Findings for Baseline" });
    within(found).getByText("The scores rank with the value of Speed (0.90).");
    expect(screen.queryByRole("list", { name: "Findings for Forest" })).toBeNull();
  });

  it("starts with three runs and lets more join up to the limit", async () => {
    const finished = Array.from({ length: DOJO_LIMITS.comparedRuns + 1 }, (_, index) => run(`r${index}`, `Run ${index}`));
    vi.mocked(dojoApi.runs).mockResolvedValue({ items: finished, next_offset: null });
    vi.mocked(dojoApi.compare).mockImplementation(async (_, ids) => ({ dataset_id: "d1", labels: [label],
      runs: ids.map(id => metrics(id, id, 1, 0)) }));
    mount("/dojo?dataset=d1&tab=compare");
    await screen.findByRole("table", { name: "Run metrics" });
    expect(dojoApi.compare).toHaveBeenLastCalledWith("d1", ["r0", "r1", "r2"], expect.any(AbortSignal));
    for (let index = 3; index < DOJO_LIMITS.comparedRuns; index++) {
      fireEvent.click(screen.getByRole("checkbox", { name: `Run ${index}` }));
    }
    const all = finished.slice(0, DOJO_LIMITS.comparedRuns).map(item => item.id);
    await waitFor(() => expect(dojoApi.compare).toHaveBeenLastCalledWith("d1", all, expect.any(AbortSignal)));
    expect(DOJO_LIMITS.comparedRuns).toBeGreaterThan(3);
    expect((screen.getByRole("checkbox", { name: `Run ${DOJO_LIMITS.comparedRuns}` }) as HTMLInputElement).disabled).toBe(true);
    screen.getByText(`${DOJO_LIMITS.comparedRuns} of at most ${DOJO_LIMITS.comparedRuns} compared`);
  });

  it("saves a finished run as a template and opens Monitoring with its recorded readings", async () => {
    vi.mocked(dojoApi.promoteRun).mockResolvedValue({ pipeline_id: "p9", pipeline_name: "Pump forest", bindings: [
      { slot_id: "voltage", slot_label: "Voltage", series_name: "Voltage", reading_id: "r1" },
      { slot_id: "load", slot_label: "Load", series_name: "Load", reading_id: null },
    ] });
    const router = mount("/dojo?dataset=d1&tab=runs");
    await screen.findByRole("table", { name: "Runs" });
    expect(screen.queryByRole("button", { name: "Use as template" })).toBeNull();
    cleanup(); router.dispose();
    access.monitors = true;
    const next = mount("/dojo?dataset=d1&tab=runs");
    const row = (await screen.findByText("Forest")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Use as template" }));
    const name = await screen.findByRole("textbox", { name: "Template name" }) as HTMLInputElement;
    expect(name.value).toBe("Forest");
    fireEvent.change(name, { target: { value: "Pump forest" } });
    fireEvent.click(screen.getByRole("button", { name: "Save template" }));
    expect(await screen.findByText(/choose a live reading in Monitoring/)).toBeTruthy();
    expect(dojoApi.promoteRun).toHaveBeenCalledWith("r1", { name: "Pump forest", description: "" });
    fireEvent.click(screen.getByRole("button", { name: "Start a monitor" }));
    await waitFor(() => expect(next.state.location.pathname).toBe("/"));
    expect(next.state.location.search).toBe("?pipeline=p9&bind=voltage%3Ar1");
  });

  it("explains the missing permission instead of showing datasets", async () => {
    access.allowed = false;
    mount("/dojo");
    await screen.findByRole("heading", { name: "The Dojo is not open to you" });
    expect(dojoApi.datasets).not.toHaveBeenCalled();
  });
});
