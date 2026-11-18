import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DojoWorkspace } from "@/features/dojo/DojoWorkspace";
import { dojoApi } from "@/features/dojo/api";
import { describePValue, sharedSeriesNames, studyProgress } from "@/features/dojo/suites";
import { pipelinesApi } from "@/features/pipelines/api";
import type { DatasetSummary, StudySummary, StudyTotals, SuiteView } from "@/types/dojo.generated";

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
  reviewSuite: vi.fn(), compareStudies: vi.fn(), study: vi.fn(), createStudy: vi.fn(), cancelStudy: vi.fn(), deleteStudy: vi.fn(),
} }));
vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { catalog: vi.fn(), list: vi.fn(), get: vi.fn() } }));

const T0 = "2024-01-01T00:00:00Z";
const datasets: DatasetSummary[] = ["Pump A", "Pump B"].map((name, index) => ({
  id: `d${index}`, name, description: "", origin: "benchmark", point_count: 1000, series_count: 1,
  start_at: T0, end_at: T0, created_by: 1, created_at: T0,
}));
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
  it("lists suites beside datasets and says when an agent's suite waits for review", async () => {
    mount("/dojo");
    const table = await screen.findByRole("table", { name: "Benchmark suites" });
    expect(within(table).getByRole("link", { name: "Pumps" }).getAttribute("href")).toBe("/dojo?suite=s1");
    expect(within(table).getByText("Agent Night")).toBeTruthy();
    expect(within(table).getByText("Not yet reviewed")).toBeTruthy();
  });

  it("creates a suite from chosen datasets in the order they were chosen", async () => {
    vi.mocked(dojoApi.createSuite).mockResolvedValue({ ...suite, id: "s2" });
    const router = mount("/dojo");
    fireEvent.click(await screen.findByRole("button", { name: "New suite" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Both pumps" } });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Pump B/ }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Pump A/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    await waitFor(() => expect(dojoApi.createSuite).toHaveBeenCalledWith(
      { name: "Both pumps", description: "", dataset_ids: ["d1", "d0"] }));
    await waitFor(() => expect(router.state.location.search).toBe("?suite=s2"));
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
