import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DojoWorkspace } from "@/features/dojo/DojoWorkspace";
import { dojoApi } from "@/features/dojo/api";
import { ProtocolPanel } from "@/features/dojo/ProtocolPanel";
import { FaultSuiteDialog } from "@/features/dojo/SuiteDialogs";
import { caughtFrom, describePValue, formatLevel, sharedSeriesNames, studyProgress } from "@/features/dojo/suites";
import { pipelinesApi } from "@/features/pipelines/api";
import type { DatasetSummary, DatasetView, ProtocolFamily, ProtocolReport, StudySummary, StudyTotals, SuiteView }
  from "@/types/dojo.generated";

const access = vi.hoisted(() => ({ guest: false }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: !access.guest, isGuest: access.guest,
  can: (permission: string) => !access.guest && permission === "use_dojo" }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/features/workspace/catalogue-context", () => ({
  useCatalogue: () => ({ selected: undefined, streamIds: [], selectSource: vi.fn(), document: { readings: [] } }),
}));
vi.mock("@/features/workspace/SelectedSourceBar", () => ({ SelectedSourceBar: () => null }));
vi.mock("@/features/dojo/api", () => ({ dojoApi: {
  datasets: vi.fn(), dataset: vi.fn(), run: vi.fn(), suites: vi.fn(), suite: vi.fn(), createSuite: vi.fn(), deleteSuite: vi.fn(),
  reviewSuite: vi.fn(), deleteDataset: vi.fn(), createFaultSuite: vi.fn(), compareStudies: vi.fn(), study: vi.fn(), createStudy: vi.fn(), cancelStudy: vi.fn(), deleteStudy: vi.fn(),
} }));
vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { catalog: vi.fn(), list: vi.fn(), get: vi.fn() } }));

const T0 = "2024-01-01T00:00:00Z";
const datasets: DatasetSummary[] = ["Pump A", "Pump B"].map((name, index) => ({
  id: `d${index}`, name, description: "", origin: "benchmark", point_count: 1000, series_count: 1,
  start_at: T0, end_at: T0, created_by: 1, created_at: T0,
}));
const own: DatasetSummary = { ...datasets[0]!, id: "d5", name: "Boiler", origin: "history" };
const totals = (vus: number): StudyTotals => ({ runs_scored: 2, labels_scored: 2, labels_detected: 2, detection_rate: 1,
  median_false_alarms_per_day: 0.5, pr_auc: vus, pr_auc_runs: 2, vus_pr: vus, vus_pr_runs: 2, auroc: 0.9, auroc_runs: 2,
  top1_hits: 2, top1_runs: 2 });
const study = (id: string, name: string, vus: number, complete = true): StudySummary => ({
  id, suite_id: "s1", name, strategy: "adaptive_stream", runs: complete ? { succeeded: 2 } : { queued: 1, succeeded: 1 },
  complete, totals: totals(vus), metrics_pending: 0, created_by: 1, created_at: T0 });
const suite: SuiteView = {
  id: "s1", name: "Pumps", description: "Two pumps", derived_from: null, datasets: 2, studies: 3, created_by: null,
  created_by_agent: "Night", reviewed: false, created_at: T0,
  items: datasets.map(item => ({ dataset_id: item.id, name: item.name, origin: "benchmark", series_names: ["value"],
    point_count: 1000, labels: 1 })),
  leaderboard: [study("st1", "Forest", 0.6), study("st2", "Baseline", 0.3)],
  unfinished: [study("st3", "Pending", 0.1, false)],
};

function mount(path: string) {
  const router = createMemoryRouter([{ path: "/dojo", element: <DojoWorkspace /> }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  vi.clearAllMocks();
  access.guest = false;
  vi.mocked(dojoApi.datasets).mockResolvedValue({ items: datasets, next_offset: null });
  vi.mocked(dojoApi.suites).mockResolvedValue({ items: [suite], next_offset: null });
  vi.mocked(dojoApi.suite).mockResolvedValue(suite);
  vi.mocked(dojoApi.compareStudies).mockResolvedValue({ suite_id: "s1", metric: "vus_pr", baseline: "st2", challenger: "st1",
    datasets: datasets.map(item => ({ dataset_id: item.id, dataset_name: item.name, baseline: 0.3, challenger: 0.6, delta: 0.3 })),
    compared: 2, wins: 2, losses: 0, ties: 0, mean_delta: 0.3, median_delta: 0.3, p_value: 0.5 });
});
afterEach(cleanup);

describe("Dojo benchmark suites", () => {
  it("keeps benchmarks apart from your own datasets and says when an agent's suite waits for review", async () => {
    vi.mocked(dojoApi.datasets).mockResolvedValue({ items: [...datasets, own], next_offset: null });
    mount("/dojo");
    const mine = await screen.findByRole("table", { name: "Datasets" });
    expect(within(mine).getAllByRole("link").map(link => link.textContent)).toEqual(["Boiler"]);
    expect(screen.queryByRole("table", { name: "Benchmark suites" })).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: /Benchmarks/ }));
    const table = await screen.findByRole("table", { name: "Benchmark suites" });
    expect(within(table).getByRole("link", { name: "Pumps" }).getAttribute("href")).toBe("/dojo?view=benchmarks&suite=s1");
    expect(within(table).getByText("By agent Night, not yet reviewed")).toBeTruthy();
    const series = screen.getByRole("table", { name: "Public series" });
    expect(within(series).getAllByRole("link").map(link => link.textContent)).toEqual(["Pump A", "Pump B"]);
  });

  it("orders a list by the header pressed, largest first for numbers", async () => {
    vi.mocked(dojoApi.datasets).mockResolvedValue({ items: datasets.map((item, index) => ({ ...item, point_count: 10 + index * 5 })), next_offset: null });
    mount("/dojo?view=benchmarks");
    const series = await screen.findByRole("table", { name: "Public series" });
    fireEvent.click(within(series).getByRole("button", { name: "Values" }));
    expect(within(series).getAllByRole("link").map(link => link.textContent)).toEqual(["Pump B", "Pump A"]);
    fireEvent.click(within(series).getByRole("button", { name: "Values" }));
    expect(within(series).getAllByRole("link").map(link => link.textContent)).toEqual(["Pump A", "Pump B"]);
  });

  it("deletes the selected suites before the selected datasets", async () => {
    const order: string[] = [];
    vi.mocked(dojoApi.deleteSuite).mockImplementation(async id => { order.push(`suite ${id}`); });
    vi.mocked(dojoApi.deleteDataset).mockImplementation(async id => { order.push(`dataset ${id}`); });
    mount("/dojo?view=benchmarks");
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Pump A" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Pumps" }));
    const bar = screen.getByRole("region", { name: "Selection" });
    expect(within(bar).getByText("2 selected")).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Delete selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(order).toEqual(["suite s1", "dataset d0"]));
  });

  it("selects a whole list at once and reports what could not be deleted", async () => {
    vi.mocked(dojoApi.deleteDataset).mockImplementation(async id => { if (id === "d1") throw new Error("Pump B is in a suite."); });
    mount("/dojo?view=benchmarks");
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select all public series" }));
    fireEvent.click(within(screen.getByRole("region", { name: "Selection" })).getByRole("button", { name: "Delete selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/1 could not be deleted\. Pump B: Pump B is in a suite\./)).toBeTruthy();
    expect(dojoApi.deleteSuite).not.toHaveBeenCalled();
  });

  it("creates a suite from chosen datasets in the order they were chosen", async () => {
    vi.mocked(dojoApi.createSuite).mockResolvedValue({ ...suite, id: "s2" });
    const router = mount("/dojo?view=benchmarks");
    fireEvent.click(await screen.findByRole("button", { name: "New suite" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Both pumps" } });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Pump B/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Pump A/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(dojoApi.createSuite).toHaveBeenCalledWith(
      { name: "Both pumps", description: "", dataset_ids: ["d1", "d0"] }));
    await waitFor(() => expect(router.state.location.search).toBe("?view=benchmarks&suite=s2"));
  });

  it("ranks complete studies, keeps unfinished ones apart and compares two", async () => {
    mount("/dojo?suite=s1");
    const ranked = await screen.findByRole("table", { name: "Ranked studies" });
    const rows = within(ranked).getAllByRole("row").slice(1);
    expect(rows.map(row => within(row).getAllByRole("cell")[1]!.textContent)).toEqual(["Forest", "Baseline"]);
    expect(within(screen.getByRole("table", { name: "Unfinished studies" })).getByText("1 waiting or running")).toBeTruthy();
    await waitFor(() => expect(dojoApi.compareStudies).toHaveBeenCalledWith("s1",
      { baseline: "st2", challenger: "st1", metric: "vus_pr" }, expect.anything()));
    expect(await screen.findByText(/better on 2, worse on 0/)).toHaveProperty("textContent", expect.stringContaining("could be chance"));
    fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "auroc" } });
    await waitFor(() => expect(dojoApi.compareStudies).toHaveBeenLastCalledWith("s1",
      { baseline: "st2", challenger: "st1", metric: "auroc" }, expect.anything()));
  });

  it("lets a member review a key's suite", async () => {
    vi.mocked(dojoApi.reviewSuite).mockResolvedValue({ ...suite, reviewed: true });
    mount("/dojo?suite=s1");
    fireEvent.click(await screen.findByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => expect(dojoApi.reviewSuite).toHaveBeenCalledWith("s1"));
  });

  it("starts a study with a design and leaves bindings automatic unless chosen", async () => {
    const definition = { input_slots: [{ id: "value", label: "Value" }], nodes: [], edges: [] };
    vi.mocked(pipelinesApi.catalog).mockResolvedValue({ templates: [{ id: "t1", name: "Moving distance", definition }] } as never);
    vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [], next_offset: null } as never);
    vi.mocked(dojoApi.createStudy).mockResolvedValue({ ...study("st9", "Moving distance", 0), definition: {}, bindings: {},
      alignment: { hold_intervals: 3, minimum_hold_seconds: 30 }, items: [] });
    vi.mocked(dojoApi.study).mockResolvedValue({ ...study("st9", "Moving distance", 0, false), definition: {}, bindings: {},
      alignment: { hold_intervals: 3, minimum_hold_seconds: 30 }, items: [] });
    const router = mount("/dojo?suite=s1");
    fireEvent.click(await screen.findByRole("button", { name: "New study" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Moving distance" })).toBeTruthy());
    fireEvent.change(within(dialog).getByLabelText("Design"), { target: { value: "template:t1" } });
    expect(await within(dialog).findByLabelText("Series for Value")).toHaveProperty("value", "");
    fireEvent.click(within(dialog).getByRole("button", { name: "Start study" }));
    await waitFor(() => expect(dojoApi.createStudy).toHaveBeenCalledWith(
      { suite_id: "s1", name: "Moving distance", definition, bindings: {} }));
    await waitFor(() => expect(router.state.location.search).toContain("study=st9"));
  });

  it("shows guests a suite without anything that changes it", async () => {
    access.guest = true;
    mount("/dojo?suite=s1");
    await screen.findByRole("table", { name: "Ranked studies" });
    expect(screen.queryByRole("button", { name: "New study" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("suite helpers", () => {
  it("binds only to series names every dataset has", () => {
    expect(sharedSeriesNames([{ series_names: ["u", "i"] }, { series_names: ["i", "t"] }])).toEqual(["i"]);
    expect(sharedSeriesNames([])).toEqual([]);
  });

  it("describes progress and p-values plainly", () => {
    expect(studyProgress({ runs: { running: 1, failed: 1 }, complete: false, metrics_pending: 0 }))
      .toBe("1 waiting or running, 1 failed or cancelled");
    expect(studyProgress({ runs: { succeeded: 2 }, complete: false, metrics_pending: 2 }))
      .toBe("metrics for 2 still to calculate");
    expect(describePValue(0.01)).toMatch("unlikely to be chance");
    expect(describePValue(null)).toBe("Too few datasets differ to test");
  });
});

describe("fault suites", () => {
  it("asks for a screening protocol suite with the design's windows", async () => {
    vi.mocked(dojoApi.createFaultSuite).mockResolvedValue(suite);
    const onCreated = vi.fn();
    const view: DatasetView = { ...datasets[0]!, origin: "history", source: {}, series: [] };
    render(<FaultSuiteDialog open dataset={view} onOpenChange={vi.fn()} onCreated={onCreated} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: "Screening protocol" })).toHaveProperty("checked", true);
    fireEvent.change(within(dialog).getByLabelText(/Warm-up/), { target: { value: "200" } });
    fireEvent.change(within(dialog).getByLabelText(/Window/), { target: { value: "40" } });
    fireEvent.change(within(dialog).getByLabelText("Seed"), { target: { value: "7" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(dojoApi.createFaultSuite).toHaveBeenCalledWith({ dataset_id: "d0", name: "Pump A · faults",
      protocol: "screening-v1", purpose: "practice", seed: 7, warmup_values: 200, window_values: 40 }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(suite));
  });

  it("leaves the seed to the server for a test suite", async () => {
    vi.mocked(dojoApi.createFaultSuite).mockResolvedValue(suite);
    const view: DatasetView = { ...datasets[0]!, origin: "history", source: {}, series: [] };
    render(<FaultSuiteDialog open dataset={view} onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Purpose"), { target: { value: "test" } });
    expect(within(dialog).queryByLabelText("Seed")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(dojoApi.createFaultSuite).toHaveBeenCalledWith({ dataset_id: "d0", name: "Pump A · faults",
      protocol: "screening-v1", purpose: "test", seed: 0 }));
  });

  it("asks for a reproducible suite of freely drawn faults", async () => {
    vi.mocked(dojoApi.createFaultSuite).mockResolvedValue(suite);
    const onCreated = vi.fn();
    const view: DatasetView = { ...datasets[0]!, origin: "history", source: {}, series: [] };
    render(<FaultSuiteDialog open dataset={view} onOpenChange={vi.fn()} onCreated={onCreated} />);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Free draw" }));
    fireEvent.change(within(dialog).getByLabelText("Copies"), { target: { value: "4" } });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Gap" }));
    fireEvent.change(within(dialog).getByLabelText("Seed"), { target: { value: "7" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(dojoApi.createFaultSuite).toHaveBeenCalledWith({ dataset_id: "d0", name: "Pump A · faults",
      copies: 4, faults_per_copy: 2, kinds: ["step", "drift", "freeze"], clean_share: 0.3, seed: 7 }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(suite));
  });

  it("needs at least one kind", async () => {
    const view: DatasetView = { ...datasets[0]!, origin: "history", source: {}, series: [] };
    render(<FaultSuiteDialog open dataset={view} onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Free draw" }));
    for (const name of ["Step", "Drift", "Frozen value", "Gap"]) fireEvent.click(within(dialog).getByRole("checkbox", { name }));
    expect(within(dialog).getByRole("button", { name: "Create suite" })).toHaveProperty("disabled", true);
  });
});

describe("protocol report", () => {
  const level = (value: number, caught: number) => ({ level: value, faults: 2, scored: 2, caught, confounded: 0,
    rate: caught / 2, low: 0, high: 1, simple_rules: 0 });
  const family = (fields: Partial<ProtocolFamily>): ProtocolFamily => ({ family: "step", title: "Sudden step",
    measure: "sigmas", sanity: false, faults: 8, scored: 8, caught: 5, chance_detections: 0.1, adjusted_detection_rate: 0.6,
    half: 2.1, ninety: 4.4, median_delay_seconds: 120, median_sigmas_at_detection: null, simple_rules_caught: 2,
    levels: [level(1, 0), level(2, 1), level(4, 2), level(8, 2)], ...fields });
  const report: ProtocolReport = { protocol: "screening-v1", version: 1, purpose: "practice", seed: 3, warmup_values: 200,
    window_values: 40, clean_run_id: "r0", false_alarms_per_day: 0.4, alarm_share: 0.002, budget_per_day: 1,
    budget_share: 0.01, within_budget: true, adjusted_detection_rate: 0.3, faults: 16, caught: 5, simple_rules_caught: 2,
    sanity_missed: 0, untestable: [], headline: "0.4 false alarms a day; catches sudden step from 2.1σ.",
    families: [family({}), family({ family: "noise", title: "Rising noise", measure: "factor", half: null, ninety: null,
      caught: 0, levels: [level(2, 0), level(4, 0), level(8, 0)] })] };

  it("leads with the budget and gives each family where its catches start", () => {
    render(<ProtocolPanel report={report} />);
    expect(screen.getByText(report.headline)).toBeTruthy();
    expect(screen.getByText("Within the false-alarm budget")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]!).getByText("from 2.1σ")).toBeTruthy();
    expect(within(rows[1]!).getByText("4.4σ")).toBeTruthy();
    expect(within(rows[2]!).getByText("not up to ×8")).toBeTruthy();
  });

  it("formats sizes as the family measures them", () => {
    expect(formatLevel({ measure: "sigmas" }, 2.345)).toBe("2.3σ");
    expect(formatLevel({ measure: "factor" }, 4)).toBe("×4");
    expect(formatLevel({ measure: "values" }, null)).toBe("–");
    expect(caughtFrom(family({ measure: "values", caught: 3, scored: 6 }))).toBe("3 of 6");
  });
});
