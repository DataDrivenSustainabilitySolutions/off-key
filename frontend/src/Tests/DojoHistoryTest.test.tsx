import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dojoApi } from "@/features/dojo/api";
import { normalizeDefinition } from "@/features/pipelines/contracts";
import { HistoryTestPanel, HistoryTestStatus } from "@/features/dojo/HistoryTest";
import { HistoryTestValues } from "@/features/dojo/HistoryTestValues";
import {
  alarmMarks, bindSeries, createHistoryTest, ruleShape, seriesComplete, stepValue, stepValues, testFigures, testProgress,
  testSpans, testStatus,
} from "@/features/dojo/historyTest";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import type {
  DatasetSeriesView, DatasetView, OutlineBucket, RunMetrics, RunOutline, RunView, StepSample,
} from "@/types/dojo.generated";

vi.mock("@/features/dojo/api", () => ({ dojoApi: {
  datasets: vi.fn(), dataset: vi.fn(), importHistory: vi.fn(), createRun: vi.fn(), run: vi.fn(), cancelRun: vi.fn(),
  metrics: vi.fn(), outline: vi.fn(), steps: vi.fn(),
} }));

const T0 = "2024-01-01T00:00:00Z";
const T1 = "2024-01-08T00:00:00Z";
const definition = normalizeDefinition({
  input_slots: [{ id: "voltage", label: "Voltage", unit: "V" }, { id: "current", label: "Current", unit: "A" }],
  nodes: [{ id: "input", kind: "source", component: "source.aligned" }],
});
const slots = definition.input_slots;
const readings = { voltage: "r-voltage", current: "r-current" };
const series = (id: string, name: string, unit: string | null, reading: string | null, position = 0): DatasetSeriesView =>
  ({ id, position, name, unit, reading_id: reading, point_count: 100, start_at: T0, end_at: T1 });
const dataset = (id: string, name: string, items: DatasetSeriesView[]): DatasetView => ({
  id, name, description: "", origin: "history", point_count: 200, series_count: items.length, start_at: T0, end_at: T1,
  created_by: 1, created_at: T0, source: {}, series: items,
});
const copy = dataset("copy", "Room · last 7 days", [series("s1", "Voltage", "V", "r-voltage"), series("s2", "Current", "A", "r-current", 1)]);
const bench = dataset("bench", "Bench", [series("b1", "U", "V", null), series("b2", "I", "A", null, 1), series("b3", "Spare", "A", null, 2)]);
const run = (id: string, status: RunView["status"] = "queued", change: Partial<RunView> = {}): RunView => ({
  id, dataset_id: "copy", name: "", status, strategy: "adaptive_stream", points_total: 200, points_read: 0, result_count: 0,
  alarm_count: 0, error: null, created_by: 1, created_at: T0, started_at: null, finished_at: null, definition: {},
  bindings: [], alignment: {}, cancel_requested: false, stats: {}, ...change,
});
const metrics = (id: string, change: Partial<RunMetrics> = {}): RunMetrics => ({
  run_id: id, run_name: "", strategy: "adaptive_stream", scored_from: "2024-01-02T12:00:00Z", scored_to: T1,
  labels_total: 0, labels_scored: 0, labels_detected: 0, detection_rate: null, median_delay_seconds: null,
  max_delay_seconds: null, alarm_count: 12, false_alarms: 4, evaluated_seconds: 475_200, false_alarms_per_day: 4 * 86_400 / 475_200,
  labels: [], ...change,
});
const labelled = (id: string, detected: number, falseAlarms: number) => metrics(id, {
  labels_total: 2, labels_scored: 2, labels_detected: detected, detection_rate: detected / 2,
  median_delay_seconds: detected ? 150 : null, false_alarms: falseAlarms, false_alarms_per_day: falseAlarms / 5,
  labels: [
    { label_id: "l1", start_at: "2024-01-04T00:00:00Z", end_at: "2024-01-04T06:00:00Z", outcome: detected ? "detected" : "missed",
      first_alarm_at: detected ? "2024-01-04T00:02:30Z" : null, delay_seconds: detected ? 150 : null },
    { label_id: "l2", start_at: "2024-01-06T00:00:00Z", end_at: "2024-01-06T06:00:00Z", outcome: detected > 1 ? "detected" : "missed",
      first_alarm_at: null, delay_seconds: null },
  ],
});
const DAY = 86_400_000;
/** A week summed up in stretches of one day; a stretch that is not named holds no results. */
const outline = (stretches: Array<Partial<OutlineBucket> & { day: number }>, strategy = "adaptive_stream"): RunOutline => ({
  run_id: "run-1", strategy, start_at: T0, end_at: T1, bucket_seconds: 86_400,
  buckets: stretches.map(({ day, ...scored }) => ({
    start_at: new Date(Date.parse(T0) + day * DAY).toISOString(), results: 10, score_min: null, score_max: null,
    threshold_min: null, threshold_max: null, alarms: 0, ...scored })),
});
const week = { start: Date.parse(T0), end: Date.parse(T1) };
/** A design with a step of every kind a test keeps values for, and a calibration, which it reports with the rule. */
const stepped = normalizeDefinition({
  input_slots: definition.input_slots,
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "scaler", kind: "transform", component: "adaptive.standard_scaler" },
    { id: "detector", kind: "detector", component: "detector:aberrant_half_space_trees" },
    { id: "calibration", kind: "calibration", component: "calibrate.fixed_split" },
    { id: "policy", kind: "policy", component: "policy.exceedance" },
  ],
});
const ready = (input: Record<string, number> | null, output: Record<string, number> | number | null) =>
  ({ input, output, state: "ready" });
const idle = (state: string, reason?: string, input: Record<string, number> | null = null) => ({ input, output: null, state, reason });
/** The first observation falls into the time the design learns; the second is scored and alarms. */
const sampled: StepSample[] = [
  { sequence: 1, timestamp: "2024-01-01T00:00:00Z", phase: "warmup", steps: {
    input: ready({ voltage: 229.5, current: 11.25 }, { voltage: 229.5, current: 11.25 }),
    scaler: idle("initializing", "Needs 50 values before its first output", { voltage: 229.5, current: 11.25 }),
    detector: idle("not_executed", "Not executed in this observation's learn pass"),
    policy: idle("not_executed", "Not executed in this observation's learn pass"),
  } },
  { sequence: 400, timestamp: "2024-01-07T12:00:00Z", phase: "operational", steps: {
    input: ready({ voltage: 231.25, current: 12.5 }, { voltage: 231.25, current: 12.5 }),
    scaler: ready({ voltage: 231.25, current: 12.5 }, { voltage: 0.4375, current: -1.123456789 }),
    detector: ready({ voltage: 0.4375, current: -1.123456789 }, 0.00001234),
    policy: ready({ score: 0.00001234 }, 1),
  } },
];
const signal = () => new AbortController().signal;

beforeEach(() => {
  vi.resetAllMocks(); clearNavigationDrafts(); cleanup();
  vi.mocked(dojoApi.datasets).mockResolvedValue({ items: [bench], next_offset: null });
  vi.mocked(dojoApi.outline).mockResolvedValue(outline([]));
});

describe("the series a design's inputs read in a test", () => {
  it("takes the series copied from an input's own reading before one that only shares its name or unit", () => {
    const items = [series("a", "Voltage", "V", null), series("b", "Mains", "V", "r-voltage", 1), series("c", "Load", "A", null, 2)];
    expect(bindSeries(slots, readings, items)).toEqual({ voltage: "b", current: "c" });
    // Without readings the Dojo's own matching decides: the name first, then the unit.
    expect(bindSeries(slots, {}, items)).toEqual({ voltage: "a", current: "c" });
  });

  it("keeps a series the member chose and gives the other inputs what is left", () => {
    expect(bindSeries(slots, {}, bench.series, { voltage: "b3" })).toEqual({ voltage: "b3", current: "b2" });
    // A choice made on another dataset names no series here.
    expect(bindSeries(slots, {}, bench.series, { voltage: "s1" })).toEqual({ voltage: "b1", current: "b2" });
  });

  it("is complete once every input has a series of its own", () => {
    expect(seriesComplete(slots, { voltage: "b1", current: "b2" })).toBe(true);
    expect(seriesComplete(slots, { voltage: "b1", current: "b1" })).toBe(false);
    expect(seriesComplete(slots, { voltage: "b1" })).toBe(false);
    expect(seriesComplete([], {})).toBe(false);
  });
});

describe("a test on history", () => {
  it("copies the recorded values of the chosen readings once and runs the design on that copy", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    const test = createHistoryTest();
    expect(test.getSnapshot().choice).toBe("window:week");
    const before = Date.now();
    await test.start({ definition, readings: { ...readings, current: "r-voltage" }, name: " Room monitor ", scope: "Room" });
    const copied = vi.mocked(dojoApi.importHistory).mock.calls[0]![0];
    expect(copied.name).toBe("Room · last 7 days");
    // Two inputs on one reading still copy it once.
    expect(copied.reading_ids).toEqual(["r-voltage"]);
    expect(Date.parse(copied.end) - Date.parse(copied.start!)).toBe(7 * 86_400_000 + 1000);
    expect(Date.parse(copied.end)).toBeGreaterThanOrEqual(before);
    const started = vi.mocked(dojoApi.createRun).mock.calls[0]![0];
    expect(started).toMatchObject({ dataset_id: "copy", definition });
    expect(started.name).toMatch(/^Room monitor · /);
    expect(started.alignment).toBeUndefined();
    // The copy is the choice from now on, so the next test compares on the same values.
    expect(test.getSnapshot()).toMatchObject({ choice: "copy", dataset: copy, step: undefined, error: "" });
    expect(test.getSnapshot().current?.run.id).toBe("run-1");
  });

  it("follows the run and reads its metrics as soon as it has finished", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    const test = createHistoryTest();
    await test.start({ definition, readings, name: "" });
    expect(vi.mocked(dojoApi.createRun).mock.calls[0]![0].bindings).toEqual({ voltage: "s1", current: "s2" });
    vi.mocked(dojoApi.run).mockResolvedValueOnce(run("run-1", "running", { points_read: 50 }));
    await test.refresh(signal());
    expect(dojoApi.metrics).not.toHaveBeenCalled();
    expect(testProgress(test.getSnapshot())).toEqual({ label: "Testing", share: 25 });
    expect(testStatus(test.getSnapshot())).toBe("Testing 25 %");
    vi.mocked(dojoApi.run).mockResolvedValueOnce(run("run-1", "succeeded"));
    vi.mocked(dojoApi.metrics).mockResolvedValue(metrics("run-1"));
    await test.refresh(signal());
    expect(test.getSnapshot().current?.metrics?.false_alarms).toBe(4);
    expect(testProgress(test.getSnapshot())).toBeUndefined();
    // A finished run is not read again.
    await test.refresh(signal());
    expect(dojoApi.run).toHaveBeenCalledTimes(2);
  });

  it("keeps the last finished test on the same values to compare with, and drops it on other values", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValueOnce(run("run-1")).mockResolvedValueOnce(run("run-2"))
      .mockResolvedValueOnce(run("run-3")).mockResolvedValueOnce(run("run-4", "queued", { dataset_id: "bench" }));
    vi.mocked(dojoApi.metrics).mockImplementation(async id => metrics(id));
    const finish = async (id: string, status: RunView["status"] = "succeeded") => {
      vi.mocked(dojoApi.run).mockResolvedValueOnce(run(id, status));
      await test.refresh(signal());
    };
    const test = createHistoryTest();
    await test.start({ definition, readings, name: "" });
    await finish("run-1");
    await test.start({ definition, readings, name: "" });
    // The copy is made once.
    expect(dojoApi.importHistory).toHaveBeenCalledTimes(1);
    expect(test.getSnapshot().previous?.run.id).toBe("run-1");
    // A test that failed has nothing to compare with; the one before it stays.
    await finish("run-2", "failed");
    await test.start({ definition, readings, name: "" });
    expect(test.getSnapshot().previous?.run.id).toBe("run-1");
    await finish("run-3");
    vi.mocked(dojoApi.dataset).mockResolvedValue(bench);
    await test.choose("bench");
    await test.start({ definition, readings, name: "" });
    expect(vi.mocked(dojoApi.createRun).mock.calls[3]![0]).toMatchObject({ dataset_id: "bench", bindings: { voltage: "b1", current: "b2" } });
    expect(test.getSnapshot().previous).toBeUndefined();
  });

  it("compares only with a test that read the same series of a dataset", async () => {
    vi.mocked(dojoApi.dataset).mockResolvedValue(bench);
    vi.mocked(dojoApi.createRun).mockResolvedValueOnce(run("run-1", "queued", { dataset_id: "bench" }))
      .mockResolvedValueOnce(run("run-2", "queued", { dataset_id: "bench" }));
    vi.mocked(dojoApi.metrics).mockImplementation(async id => metrics(id));
    const test = createHistoryTest();
    await test.choose("bench");
    await test.start({ definition, readings, name: "" });
    vi.mocked(dojoApi.run).mockResolvedValueOnce(run("run-1", "succeeded", { dataset_id: "bench" }));
    await test.refresh(signal());
    test.bind("current", "b3");
    await test.start({ definition, readings, name: "" });
    expect(vi.mocked(dojoApi.createRun).mock.calls[1]![0].bindings).toEqual({ voltage: "b1", current: "b3" });
    expect(test.getSnapshot().previous).toBeUndefined();
  });

  it("spans a test over the series it read, not over the rest of the dataset", async () => {
    const later = "2024-01-05T00:00:00Z";
    const mixed = dataset("mixed", "Mixed", [{ ...series("m1", "U", "V", null), start_at: later },
      { ...series("m2", "I", "A", null, 1), start_at: later }, series("m3", "Spare", "A", null, 2)]);
    vi.mocked(dojoApi.dataset).mockResolvedValue(mixed);
    vi.mocked(dojoApi.createRun).mockResolvedValueOnce(run("run-1", "queued", { dataset_id: "mixed" }));
    const test = createHistoryTest();
    await test.choose("mixed");
    test.bind("voltage", "m1");
    test.bind("current", "m2");
    await test.start({ definition, readings, name: "" });
    expect(test.getSnapshot().current?.dataset).toMatchObject({ start_at: later, end_at: T1 });
  });

  it("does nothing while a test is under way, reports what the server refuses and cancels on request", async () => {
    vi.mocked(dojoApi.importHistory).mockRejectedValueOnce(new Error("The chosen readings recorded nothing in this window"));
    const test = createHistoryTest();
    await test.start({ definition, readings, name: "" });
    expect(test.getSnapshot()).toMatchObject({ choice: "window:week", step: undefined,
      error: "The chosen readings recorded nothing in this window" });
    expect(dojoApi.createRun).not.toHaveBeenCalled();
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1", "running"));
    await test.start({ definition, readings, name: "" });
    await test.start({ definition, readings, name: "" });
    await test.choose("window:day");
    test.bind("voltage", "s2");
    expect(dojoApi.createRun).toHaveBeenCalledTimes(1);
    expect(test.getSnapshot()).toMatchObject({ choice: "copy", chosen: {} });
    vi.mocked(dojoApi.cancelRun).mockResolvedValue(run("run-1", "running", { cancel_requested: true }));
    await test.cancel();
    expect(testStatus(test.getSnapshot())).toBe("Stopping…");
    vi.mocked(dojoApi.run).mockResolvedValueOnce(run("run-1", "cancelled", { cancel_requested: true }));
    await test.refresh(signal());
    expect(testProgress(test.getSnapshot())).toBeUndefined();
    expect(dojoApi.metrics).not.toHaveBeenCalled();
  });

  it("reads the metrics again, since labels set in the Dojo change what the same alarms mean", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    vi.mocked(dojoApi.run).mockResolvedValue(run("run-1", "succeeded"));
    vi.mocked(dojoApi.metrics).mockResolvedValueOnce(metrics("run-1")).mockResolvedValueOnce(labelled("run-1", 1, 2));
    const test = createHistoryTest();
    await test.rescore(signal());
    expect(dojoApi.metrics).not.toHaveBeenCalled();
    await test.start({ definition, readings, name: "" });
    await test.refresh(signal());
    await test.rescore(signal());
    expect(test.getSnapshot().current?.metrics).toMatchObject({ labels_total: 2, labels_detected: 1, false_alarms: 2 });
  });
});

describe("what a finished test found", () => {
  it("counts alarms where the values have no labels, and detections, delay and false alarms where they have", () => {
    expect(testFigures(metrics("a"))).toMatchObject([{ label: "Alarms", value: "4 · 0.73 per day" }]);
    expect(testFigures(labelled("a", 1, 2)).map(item => [item.label, item.value])).toEqual([
      ["Labels detected", "1 of 2"], ["Median delay", "2.5 min"], ["False alarms", "2 · 0.4 per day"],
    ]);
  });

  it("names the figure of the test before only where it differs", () => {
    const figures = testFigures(labelled("b", 2, 2), labelled("a", 1, 2));
    expect(figures.map(item => item.before)).toEqual(["1 of 2", undefined, undefined]);
    // A figure the earlier test did not have is not compared.
    expect(testFigures(labelled("b", 2, 2), metrics("a")).every(item => item.before === undefined)).toBe(true);
  });

  it("splits the values into the time the design learned and the time it was scored", () => {
    const tested = { dataset: { id: "copy", name: "Copy", start_at: T0, end_at: T1 } };
    expect(testSpans(tested, metrics("a"))).toMatchObject({ learning: 1.5 * 86_400_000, scoring: 5.5 * 86_400_000 });
    // Nothing was scored: the design learned to the end.
    expect(testSpans(tested, metrics("a", { scored_from: null, scored_to: null })))
      .toMatchObject({ learning: 7 * 86_400_000, scoring: 0 });
    expect(testSpans({ dataset: { ...tested.dataset, end_at: null } }, metrics("a"))).toBeUndefined();
  });
});

describe("the detection rule over the tested values", () => {
  const scored = (day: number, low: number, high: number, limit: number, alarms = 0) =>
    ({ day, score_min: low, score_max: high, threshold_min: limit, threshold_max: limit, alarms });

  it("marks an alarm where its stretch of time lies on the span of the values", () => {
    expect(alarmMarks(outline([scored(2, 1, 2, 3), scored(3, 1, 5, 3, 2), scored(6, 1, 4, 3, 1)]), week)).toEqual([50, 93]);
    expect(alarmMarks(outline([{ day: 0 }]), week)).toEqual([]);
  });

  it("draws each stretch from its lowest to its highest score, against the boundary", () => {
    // The first day was spent learning, and the fifth recorded nothing.
    const shape = ruleShape(outline([{ day: 0 }, scored(2, 1, 2, 3), scored(3, 1, 5, 3, 2), scored(5, 1, 2, 4)]), week)!;
    expect(shape).toMatchObject({ kind: "score", top: "5", bottom: "1",
      summary: "Scores between 1 and 5, against a boundary between 3 and 4" });
    expect(shape.scores).toBe("M28.57 76.5h14.29V100h-14.29zM71.43 76.5h14.29V100h-14.29z");
    // The stretch that alarmed is a path of its own, and reaches above the boundary.
    expect(shape.alarmed).toBe("M42.86 6h14.29V100h-14.29z");
    // The line steps on from one stretch to the next and starts anew after the gap.
    expect(shape.boundary).toBe("M28.57 53H42.86V53H57.15M71.43 29.5H85.72");
  });

  it("keeps the boundary in view under a score far above it", () => {
    const shape = ruleShape(outline([scored(2, 1, 2, 3), scored(3, 1, 1000, 3, 1)]), week)!;
    expect(shape).toMatchObject({ top: "9", bottom: "1", summary: "Scores between 1 and 1K, against a boundary of 3" });
    expect(shape.boundary).toBe("M28.57 76.5H42.86V76.5H57.15");
    expect(shape.alarmed).toBe("M42.86 6h14.29V100h-14.29z");
  });

  it("draws p-values rarer upward and without a boundary", () => {
    const rare = (day: number, low: number, high: number, alarms = 0) => ({ day, score_min: low, score_max: high, alarms });
    const shape = ruleShape(outline([rare(2, 0.2, 0.9), rare(3, 0.0001, 0.5, 1)], "static_baseline"), week)!;
    expect(shape).toMatchObject({ kind: "p", top: "p 1e-4", bottom: "p 1", boundary: "",
      summary: "p-values between 1e-4 and 0.9; a lower one is a rarer value" });
    expect(shape.alarmed).toBe("M42.86 6h14.29V92.93h-14.29z");
    // Values that were all usual keep to the lower part: the field reaches to a p-value of 0.01 at least.
    const quiet = ruleShape(outline([rare(2, 0.3, 0.9)], "static_baseline"), week)!;
    expect(quiet.top).toBe("p 0.01");
    expect(quiet.scores).toBe("M28.57 75.42h14.29V97.85h-14.29z");
  });

  it("draws nothing for a test that scored nothing", () => {
    expect(ruleShape(outline([{ day: 0 }, { day: 1 }]), week)).toBeUndefined();
    expect(ruleShape(outline([]), week)).toBeUndefined();
  });
});

describe("the values of a step in a test", () => {
  const [learning, scored] = sampled as [StepSample, StepSample];

  it("names what went into a step and what came out, in the order the test kept them", () => {
    expect(stepValues(scored, "scaler", stepped)).toEqual({
      input: [["voltage", 231.25], ["current", 12.5]], output: [["voltage", 0.4375], ["current", -1.123456789]],
      note: undefined, borrowed: false });
    // A detector gives one number.
    expect(stepValues(scored, "detector", stepped)?.output).toEqual([["value", 0.00001234]]);
    expect([231.25, -1.123456789, 0.00001234, 0, "yes"].map(stepValue)).toEqual(["231.25", "-1.1235", "1.23e-5", "0", "yes"]);
  });

  it("shows the readings of an input once, as what it gives", () => {
    expect(stepValues(scored, "input", stepped)).toMatchObject({ input: undefined, output: [["voltage", 231.25], ["current", 12.5]] });
  });

  it("says whether the detection rule alarmed, and shows the rule for the calibration it runs", () => {
    expect(stepValues(scored, "policy", stepped)).toMatchObject({ input: [["score", 0.00001234]], output: [["alarm", "yes"]], borrowed: false });
    expect(stepValues(scored, "calibration", stepped)).toMatchObject({ output: [["alarm", "yes"]], borrowed: true });
    const quiet = { ...scored, steps: { ...scored.steps, policy: ready({ score: 0.2 }, 0) } };
    expect(stepValues(quiet, "policy", stepped)?.output).toEqual([["alarm", "no"]]);
  });

  it("says in words why a step gave nothing", () => {
    // The runtime's reason where it is a sentence of its own, with what went in.
    expect(stepValues(learning, "scaler", stepped)).toMatchObject({
      input: [["voltage", 229.5], ["current", 11.25]], output: undefined, note: "Needs 50 values before its first output." });
    expect(stepValues(learning, "detector", stepped)).toMatchObject({
      input: undefined, output: undefined, note: "Did not run for this observation: the design was still learning." });
    const held = { ...scored, steps: { scaler: idle("held_back", "The condition does not hold for this observation"),
      detector: idle("waiting_for_dependency"), policy: idle("rejected") } };
    expect(["scaler", "detector", "policy"].map(node => stepValues(held, node, stepped)?.note)).toEqual([
      "The condition does not hold for this observation.", "Waiting for a step before it.", "Skipped this observation."]);
    // A step added since the test, or one the test kept nothing for.
    expect(stepValues(scored, "added", stepped)).toBeUndefined();
  });
});

describe("the test panel", () => {
  const onChooseReadings = vi.fn();
  function Panel({ bound = readings, blocked, changed = definition }: {
    bound?: Record<string, string | undefined>; blocked?: string; changed?: typeof definition;
  }) {
    // The composer's button follows the run; the panel beside it shows the same test.
    return <>
      <button type="button"><HistoryTestStatus session="panel" open /></button>
      <HistoryTestPanel session="panel" definition={changed} readings={bound} name="Room monitor" scope="Room"
        blocked={blocked} onChooseReadings={onChooseReadings} />
    </>;
  }
  const mount = (props: Parameters<typeof Panel>[0] = {}) => render(<MemoryRouter><Panel {...props} /></MemoryRouter>);
  const values = () => screen.getByRole("combobox", { name: "Values" }) as HTMLSelectElement;
  const figure = (result: ReturnType<typeof within>, name: string) =>
    result.getByText(name, { selector: "dt" }).nextElementSibling?.textContent;
  const finishes = (found: RunMetrics) => {
    vi.mocked(dojoApi.run).mockImplementation(async id => run(id, "succeeded"));
    vi.mocked(dojoApi.metrics).mockResolvedValue(found);
  };

  it("offers the recorded values of the chosen readings and the datasets of the Dojo", async () => {
    mount();
    expect(values().value).toBe("window:week");
    expect(within(values()).getAllByRole("option").map(item => item.textContent)).toEqual(["Last 24 hours", "Last 7 days", "Last 30 days"]);
    await screen.findByRole("option", { name: "Bench" });
    expect(screen.getByText(/copied into a Dojo dataset first/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Run test" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("says why a design cannot be tested yet, and leads to the readings where they are missing", async () => {
    const view = mount({ blocked: "The design is not ready to run." });
    await screen.findByRole("option", { name: "Bench" });
    expect((screen.getByRole("button", { name: "Run test" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("The design is not ready to run.");
    expect(screen.queryByRole("button", { name: "Choose readings" })).toBeNull();
    view.unmount();
    mount({ bound: { voltage: "r-voltage" } });
    await screen.findByRole("option", { name: "Bench" });
    expect((screen.getByRole("button", { name: "Run test" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("Choose a reading for every input first.");
    fireEvent.click(screen.getByRole("button", { name: "Choose readings" }));
    expect(onChooseReadings).toHaveBeenCalledTimes(1);
  });

  it("runs the test, shows how far it is and then what it found", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1", "running", { points_read: 50 }));
    let finish: (run: RunView) => void = () => {};
    vi.mocked(dojoApi.run).mockImplementation(() => new Promise<RunView>(resolve => { finish = resolve; }));
    vi.mocked(dojoApi.metrics).mockResolvedValue(metrics("run-1"));
    vi.mocked(dojoApi.outline).mockResolvedValue(outline([
      { day: 0 }, { day: 2, score_min: 1, score_max: 2, threshold_min: 3, threshold_max: 3 },
      { day: 4, score_min: 1, score_max: 5, threshold_min: 3, threshold_max: 3, alarms: 6 }]));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));
    const bar = await screen.findByRole("progressbar", { name: "Test progress" });
    expect(bar.getAttribute("aria-valuenow")).toBe("25");
    expect(screen.getByRole("status").textContent).toBe("Testing");
    // The button that opens the panel keeps its word and fills a line instead.
    const opener = screen.getByRole("button", { name: "Test on history, testing 25 %" });
    expect(opener.textContent).toBe("Test on history, testing 25 %");
    expect((opener.querySelector(".dj-test-meter") as HTMLElement).style.width).toBe("25%");
    expect(values().disabled).toBe(true);
    // The copy is the chosen dataset now, listed although the list was read before it existed.
    expect(values().value).toBe("copy");
    expect(screen.getByRole("option", { name: "Room · last 7 days" })).toBeTruthy();
    await waitFor(() => expect(dojoApi.run).toHaveBeenCalled());
    finish(run("run-1", "succeeded"));
    const result = within(await screen.findByRole("region", { name: "Test result" }));
    expect(figure(result, "Alarms")).toBe("4 · 0.73 per day");
    expect(figure(result, "Learning")).toBe("1.5 d");
    expect(figure(result, "Scored")).toBe("5.5 d");
    expect(result.getByText(/These values have no labels yet/)).toBeTruthy();
    expect(result.getByRole("link", { name: "Open in the Dojo" }).getAttribute("href")).toBe("/dojo?dataset=copy");
    // Alarms and scores are read summed up over time, in one request.
    const strip = await result.findByRole("img", { name: /^Alarms between/ });
    expect(Array.from(strip.querySelectorAll("i"), item => item.style.left)).toEqual(["64.5%"]);
    expect(result.getByRole("img", { name: "Scores between 1 and 5, against a boundary of 3" }).querySelectorAll("path")).toHaveLength(3);
    expect(result.getByText("Score")).toBeTruthy();
    expect(result.getByText("Boundary")).toBeTruthy();
    expect(dojoApi.outline).toHaveBeenCalledWith("run-1", { buckets: 200 }, expect.anything());
    expect(screen.getByRole("button", { name: "Test again" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Test on history" }).querySelector(".dj-test-meter")).toBeNull();
  });

  it("scores against labels, compares with the test before and says when the design has changed since", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValueOnce(run("run-1")).mockResolvedValueOnce(run("run-2"));
    finishes(labelled("run-1", 1, 4));
    const view = mount();
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));
    let result = within(await screen.findByRole("region", { name: "Test result" }));
    expect(figure(result, "Labels detected")).toBe("1 of 2");
    expect(figure(result, "Median delay")).toBe("2.5 min");
    expect(result.getByRole("link", { name: "Compare runs in the Dojo" }).getAttribute("href")).toBe("/dojo?dataset=copy&tab=compare");
    expect(result.queryByText(/has changed since/)).toBeNull();
    const changed = { ...definition, nodes: [...definition.nodes, { ...definition.nodes[0]!, id: "other" }] };
    view.rerender(<MemoryRouter><Panel changed={changed} /></MemoryRouter>);
    expect(result.getByText("The design has changed since this test.")).toBeTruthy();
    finishes(labelled("run-2", 2, 1));
    fireEvent.click(screen.getByRole("button", { name: "Test again" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Test result" }).textContent).toContain("2 of 2"));
    result = within(screen.getByRole("region", { name: "Test result" }));
    expect(figure(result, "Labels detected")).toBe("2 of 2before 1 of 2");
    expect(figure(result, "False alarms")).toBe("1 · 0.2 per daybefore 4 · 0.8 per day");
    expect(result.queryByText(/has changed since/)).toBeNull();
    expect(vi.mocked(dojoApi.createRun).mock.calls[1]![0].definition).toBe(changed);
  });

  it("says so when the alarms and scores of a finished test cannot be read", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    finishes(metrics("run-1"));
    vi.mocked(dojoApi.outline).mockRejectedValue(new Error("The service is busy."));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));
    const result = within(await screen.findByRole("region", { name: "Test result" }));
    expect((await result.findByRole("alert")).textContent).toBe("The alarms and scores could not be drawn. The service is busy.");
    // The strip does not claim that nothing alarmed, and the figures stand without it.
    expect(result.getByRole("img").getAttribute("aria-label")).toMatch(/^Learning and labels between/);
    expect(figure(result, "Alarms")).toBe("4 · 0.73 per day");
  });

  it("asks which series feeds which input on values that were not copied from the readings", async () => {
    vi.mocked(dojoApi.dataset).mockResolvedValue(bench);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    finishes(metrics("run-1", { scored_from: null, scored_to: null, false_alarms: 0, false_alarms_per_day: null }));
    mount();
    fireEvent.change(values(), { target: { value: (await screen.findByRole("option", { name: "Bench" }) as HTMLOptionElement).value } });
    const voltage = await screen.findByRole("combobox", { name: "Series for Voltage" }) as HTMLSelectElement;
    const current = screen.getByRole("combobox", { name: "Series for Current" }) as HTMLSelectElement;
    expect([voltage.value, current.value]).toEqual(["b1", "b2"]);
    fireEvent.change(current, { target: { value: "b3" } });
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));
    await waitFor(() => expect(dojoApi.createRun).toHaveBeenCalled());
    expect(dojoApi.importHistory).not.toHaveBeenCalled();
    expect(vi.mocked(dojoApi.createRun).mock.calls[0]![0]).toMatchObject({ dataset_id: "bench", bindings: { voltage: "b1", current: "b3" } });
    // The design learned to the end of the values: nothing to count, and a way on.
    const result = within(await screen.findByRole("region", { name: "Test result" }));
    expect(result.getByText(/still learning when the values ended/)).toBeTruthy();
    expect(result.queryByText("Alarms")).toBeNull();
    expect(figure(result, "Learning")).toBe("7 d");
  });

  describe("with the settings of a step", () => {
    const onOpenTest = vi.fn();
    function Composer({ node = "scaler", changed = stepped }: { node?: string; changed?: typeof stepped }) {
      return <>
        <Panel changed={changed} />
        <HistoryTestValues session="panel" node={node} definition={changed} onOpenTest={onOpenTest} />
      </>;
    }
    const compose = (props: Parameters<typeof Composer>[0] = {}) => render(<MemoryRouter><Composer {...props} /></MemoryRouter>);
    const fold = () => screen.getByText("Values in the last test").closest("details")!;
    // jsdom does not toggle a details element on a click of its summary.
    const unfold = (open = true) => { fold().open = open; fireEvent(fold(), new Event("toggle")); };
    const side = (name: string) => Array.from(
      screen.getByRole("heading", { name, level: 5 }).parentElement!.querySelectorAll("dl > div"), item => item.textContent);
    const tested = async () => {
      vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
      vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
      finishes(metrics("run-1"));
      vi.mocked(dojoApi.steps).mockResolvedValue({ run_id: "run-1", samples: sampled });
      fireEvent.click(screen.getByRole("button", { name: "Run test" }));
      await screen.findByRole("region", { name: "Test result" });
    };

    it("stays folded until asked for, and leads to the test where there is none yet", async () => {
      compose();
      expect(fold().open).toBe(false);
      expect(screen.queryByText(/Test the design on history/)).toBeNull();
      unfold();
      expect(await screen.findByText(/Test the design on history to see the values that go into this step/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Open the test" }));
      expect(onOpenTest).toHaveBeenCalledTimes(1);
      expect(dojoApi.steps).not.toHaveBeenCalled();
    });

    it("shows the latest observation of the finished test, and reads it only once unfolded", async () => {
      compose();
      await tested();
      expect(dojoApi.steps).not.toHaveBeenCalled();
      unfold();
      expect((await screen.findByText(/^Observation 2 of 2 · /)).getAttribute("role")).toBe("status");
      expect(dojoApi.steps).toHaveBeenCalledWith("run-1");
      expect(side("In")).toEqual(["voltage231.25", "current12.5"]);
      expect(side("Out")).toEqual(["voltage0.4375", "current-1.1235"]);
      expect((screen.getByRole("button", { name: "Later observation" }) as HTMLButtonElement).disabled).toBe(true);
    });

    it("keeps the observation from step to step, so one set of readings can be followed through the design", async () => {
      const view = compose();
      await tested();
      unfold();
      await screen.findByText(/^Observation 2 of 2 · /);
      fireEvent.click(screen.getByRole("button", { name: "Earlier observation" }));
      expect(screen.getByText(/^Observation 1 of 2 · /)).toBeTruthy();
      expect((screen.getByRole("button", { name: "Earlier observation" }) as HTMLButtonElement).disabled).toBe(true);
      expect(side("In")).toEqual(["voltage229.5", "current11.25"]);
      expect(screen.getByText("Needs 50 values before its first output.")).toBeTruthy();
      view.rerender(<MemoryRouter><Composer node="detector" /></MemoryRouter>);
      expect(screen.getByText(/^Observation 1 of 2 · /)).toBeTruthy();
      expect(screen.getByText("Did not run for this observation: the design was still learning.")).toBeTruthy();
      expect(screen.queryByRole("heading", { name: "In", level: 5 })).toBeNull();
      view.rerender(<MemoryRouter><Composer node="calibration" /></MemoryRouter>);
      fireEvent.click(screen.getByRole("button", { name: "Later observation" }));
      expect(screen.getByText(/Calibration runs inside the detection rule/)).toBeTruthy();
      expect(side("Out")).toEqual(["alarmyes"]);
      // The fold holds too, and a step the test did not know says so.
      const changed = { ...stepped, nodes: [...stepped.nodes, { ...stepped.nodes[1]!, id: "added" }] };
      view.rerender(<MemoryRouter><Composer node="added" changed={changed} /></MemoryRouter>);
      expect(fold().open).toBe(true);
      expect(screen.getByText("The last test has no values for this step. Test again to see them.")).toBeTruthy();
      expect(within(fold()).getByText("The design has changed since this test.")).toBeTruthy();
      expect(dojoApi.steps).toHaveBeenCalledTimes(1);
    });

    it("says so while a test runs, when it gave no results and when its values cannot be read", async () => {
      vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
      vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1", "running"));
      let finish: (run: RunView) => void = () => {};
      vi.mocked(dojoApi.run).mockImplementation(() => new Promise<RunView>(resolve => { finish = resolve; }));
      vi.mocked(dojoApi.metrics).mockResolvedValue(metrics("run-1"));
      vi.mocked(dojoApi.steps).mockRejectedValueOnce(new Error("The service is busy."))
        .mockResolvedValue({ run_id: "run-1", samples: [] });
      compose();
      unfold();
      fireEvent.click(screen.getByRole("button", { name: "Run test" }));
      expect(await screen.findByText(/^The test is running\. The values that go into this step/)).toBeTruthy();
      await waitFor(() => expect(dojoApi.run).toHaveBeenCalled());
      finish(run("run-1", "succeeded"));
      expect((await within(fold()).findByRole("alert")).textContent).toBe("The values could not be read. The service is busy.");
      // Unfolding again reads them again.
      unfold(false);
      unfold();
      expect(await screen.findByText("The last test gave no results, so it has no values to show.")).toBeTruthy();
      expect(dojoApi.steps).toHaveBeenCalledTimes(2);
    });
  });

  it("shows why a run stopped", async () => {
    vi.mocked(dojoApi.importHistory).mockResolvedValue(copy);
    vi.mocked(dojoApi.createRun).mockResolvedValue(run("run-1"));
    vi.mocked(dojoApi.run).mockResolvedValue(run("run-1", "failed", { error: "The detector received no finite values" }));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The test stopped. The detector received no finite values");
    expect(dojoApi.metrics).not.toHaveBeenCalled();
  });
});
