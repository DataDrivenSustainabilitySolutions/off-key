import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DojoWorkspace } from "@/features/dojo/DojoWorkspace";
import { dojoApi } from "@/features/dojo/api";
import { pipelinesApi } from "@/features/pipelines/api";
import type { Comparison, DatasetView, LabelView, RunMetrics, RunSummary } from "@/types/dojo.generated";

const access = vi.hoisted(() => ({ allowed: true }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: true, can: (permission: string) => access.allowed && permission === "use_dojo" }) }));
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
    selected: { key: "pump", kind: "device", label: "Pump 1", streamIds: ["r1", "r2", "r3"] },
    document: { readings: [
      { id: "r1", label: "Voltage", unit: "V", value_type: "number" },
      { id: "r2", label: "Current", unit: "A", value_type: "number" },
      { id: "r3", label: "Mode", value_type: "text" },
    ] },
  }),
}));
vi.mock("@/features/dojo/api", () => ({ dojoApi: {
  datasets: vi.fn(), dataset: vi.fn(), importCsv: vi.fn(), importHistory: vi.fn(), changeDataset: vi.fn(), deleteDataset: vi.fn(),
  points: vi.fn(), labels: vi.fn(), createLabel: vi.fn(), changeLabel: vi.fn(), deleteLabel: vi.fn(), runs: vi.fn(), run: vi.fn(),
  createRun: vi.fn(), cancelRun: vi.fn(), deleteRun: vi.fn(), results: vi.fn(), metrics: vi.fn(), compare: vi.fn(),
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
  labels: [{ label_id: "l1", start_at: label.start_at, end_at: label.end_at, outcome: detected ? "detected" : "missed",
    first_alarm_at: detected ? "2024-01-01T00:32:00Z" : null, delay_seconds: detected ? 120 : null }] });

function mount(path: string) {
  const router = createMemoryRouter([{ path: "/dojo", element: <DojoWorkspace /> }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  vi.clearAllMocks();
  access.allowed = true;
  vi.mocked(dojoApi.datasets).mockResolvedValue({ items: [dataset], next_offset: null });
  vi.mocked(dojoApi.dataset).mockResolvedValue(dataset);
  vi.mocked(dojoApi.labels).mockResolvedValue({ items: [label] });
  vi.mocked(dojoApi.points).mockResolvedValue({ items: [{ timestamp: T0, value: 1 }], next_after: null });
  vi.mocked(dojoApi.runs).mockResolvedValue({ items: [run("r1", "Forest"), run("r2", "Baseline")], next_offset: null });
  vi.mocked(dojoApi.results).mockResolvedValue({ items: [], next_after: null });
});

describe("Dojo workspace", () => {
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
      alignment: { freshness_seconds: 30, max_skew_seconds: 5 } })));
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
  });

  it("explains the missing permission instead of showing datasets", async () => {
    access.allowed = false;
    mount("/dojo");
    await screen.findByRole("heading", { name: "The Dojo is not open to you" });
    expect(dojoApi.datasets).not.toHaveBeenCalled();
  });
});
