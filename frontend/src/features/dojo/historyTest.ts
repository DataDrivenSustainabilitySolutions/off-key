import { useCallback, useSyncExternalStore } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { getErrorMessage } from "@/lib/errors";
import { createDraftStore, navigationDraft } from "@/lib/navigation-draft";
import type { DatasetSeriesView, DatasetView, RunMetrics, RunOutline, RunView, StepSample } from "@/types/dojo.generated";
import type { InputSlot, PipelineNodePreview } from "@/types/pipelines.generated";
import type { PipelineDefinition } from "../pipelines/contracts";
import type { DesignEvidence } from "../pipelines/designTest";
import { dojoApi } from "./api";
import { formatDuration, formatInstant, isActive, suggestBindings } from "./model";

const DAY_MS = 86_400_000;

/** How far back the recorded values of the chosen readings are copied for a test. */
export const TEST_WINDOWS = [
  { id: "window:day", label: "Last 24 hours", span: DAY_MS },
  { id: "window:week", label: "Last 7 days", span: 7 * DAY_MS },
  { id: "window:month", label: "Last 30 days", span: 30 * DAY_MS },
] as const;
const windowOf = (choice: string) => TEST_WINDOWS.find((item) => item.id === choice);

/** Each input of a design matched to a series of a dataset.
 *
 * The series copied from the input's own reading wins. What is left is matched by name, then by
 * unit, as the Dojo does, and a series the member chose goes before either.
 */
export function bindSeries(slots: InputSlot[], readings: Record<string, string | undefined>, series: DatasetSeriesView[],
  chosen: Record<string, string> = {}): Record<string, string> {
  const known = new Set(series.map((item) => item.id));
  const bound: Record<string, string> = {};
  for (const slot of slots) if (known.has(chosen[slot.id] ?? "")) bound[slot.id] = chosen[slot.id]!;
  const used = () => new Set(Object.values(bound));
  for (const slot of slots) {
    if (bound[slot.id] || !readings[slot.id]) continue;
    const taken = used();
    const found = series.find((item) => item.reading_id === readings[slot.id] && !taken.has(item.id));
    if (found) bound[slot.id] = found.id;
  }
  const taken = used();
  return { ...suggestBindings(slots.filter((slot) => !bound[slot.id]), series.filter((item) => !taken.has(item.id))), ...bound };
}

/** Whether every input has a series of its own. */
export function seriesComplete(slots: InputSlot[], bindings: Record<string, string>) {
  const values = slots.map((slot) => bindings[slot.id]);
  return slots.length > 0 && values.every(Boolean) && new Set(values).size === values.length;
}

export type TestedRun = {
  run: RunView;
  /** Read once the run has finished, and again when the labels may have changed. */
  metrics?: RunMetrics;
  /** The design as it was tested, to tell when it has changed since. */
  definition: PipelineDefinition;
  /** The series each input read; a test on other series is not compared with it. */
  bindings: Record<string, string>;
  /** The dataset, spanning only the series the test read. */
  dataset: Pick<DatasetView, "id" | "name" | "start_at" | "end_at">;
  /** Who ran it, where the design came with its test. */
  by?: string;
};

const sameBindings = (one: Record<string, string>, other: Record<string, string>) =>
  Object.keys(one).length === Object.keys(other).length && Object.entries(one).every(([slot, series]) => other[slot] === series);

/** From the first to the last value of the series a test read: other series of the dataset are not replayed. */
function boundSpan(dataset: DatasetView, bindings: Record<string, string>) {
  const read = new Set(Object.values(bindings));
  const series = dataset.series.filter((item) => read.has(item.id));
  const starts = series.flatMap((item) => item.start_at ? [item.start_at] : []);
  const ends = series.flatMap((item) => item.end_at ? [item.end_at] : []);
  const pick = (times: string[], earliest: boolean) => times.reduce<string | null>((best, time) =>
    best === null || (Date.parse(time) < Date.parse(best)) === earliest ? time : best, null);
  return { start_at: pick(starts, true) ?? dataset.start_at, end_at: pick(ends, false) ?? dataset.end_at };
}

type Snapshot = {
  /** A window of recorded values to copy, or the id of a Dojo dataset. */
  choice: string;
  /** The chosen dataset with its series, once it is loaded. */
  dataset?: DatasetView;
  /** The series the member chose for an input, over the suggested one. */
  chosen: Record<string, string>;
  step?: "copying" | "starting";
  current?: TestedRun;
  /** The finished test before the current one, on the same series. */
  previous?: TestedRun;
  /** Whether the values of a step in the last test are unfolded, and which of its observations they show.
   * Both hold from step to step, so one observation can be followed through the design. */
  watching?: boolean;
  observation?: number;
  /** What a few observations of a finished test looked like at every step: being read while it holds neither. */
  samples?: { run: string; items?: StepSample[]; error?: string };
  error: string;
};

export type TestRequest = {
  definition: PipelineDefinition;
  /** The reading each input monitors, by slot. */
  readings: Record<string, string | undefined>;
  /** The service's name, for the run. */
  name: string;
  /** The entity the readings belong to, for the name of a copy. */
  scope?: string;
};

const scored = (item?: TestedRun) => item?.metrics ? item : undefined;

/** One composer's tests. It outlives the panel that shows it, so a run keeps going while a step is edited. */
export function createHistoryTest() {
  const { getSnapshot, subscribe, update, isCurrent } = createDraftStore<Snapshot>(undefined,
    () => ({ choice: "window:week", chosen: {}, error: "" }), () => undefined);
  // A newer choice retires the dataset an older one was loading.
  let selection = 0;
  const busy = () => !!getSnapshot().step || (!!getSnapshot().current && isActive(getSnapshot().current!.run));
  return {
    getSnapshot,
    subscribe,
    choose: async (choice: string) => {
      if (!isCurrent() || busy()) return;
      const context = ++selection;
      update({ ...getSnapshot(), choice, dataset: undefined, chosen: {}, error: "" });
      if (windowOf(choice)) return;
      try {
        const dataset = await dojoApi.dataset(choice);
        if (context === selection) update({ ...getSnapshot(), dataset });
      } catch (reason) {
        if (context === selection) update({ ...getSnapshot(), error: getErrorMessage(reason) });
      }
    },
    bind: (slot: string, series: string) => {
      if (busy()) return;
      update({ ...getSnapshot(), chosen: { ...getSnapshot().chosen, [slot]: series } });
    },
    start: async ({ definition, readings, name, scope }: TestRequest) => {
      if (!isCurrent() || busy()) return;
      const slots = definition.input_slots;
      const window = windowOf(getSnapshot().choice);
      try {
        let { dataset } = getSnapshot();
        if (window) {
          update({ ...getSnapshot(), step: "copying", error: "" });
          const now = Date.now();
          dataset = await dojoApi.importHistory({
            name: `${(scope || name.trim() || "Recorded readings").slice(0, 100)} · ${window.label.toLowerCase()}`,
            reading_ids: [...new Set(slots.flatMap((slot) => readings[slot.id] ?? []))],
            start: new Date(now - window.span).toISOString(),
            // A second past now keeps a value that arrives while the copy starts.
            end: new Date(now + 1000).toISOString(),
          });
          // Later tests run on the same copy, so their results compare.
          selection++;
          update({ ...getSnapshot(), choice: dataset.id, dataset, chosen: {} });
        }
        if (!dataset) return;
        update({ ...getSnapshot(), step: "starting", error: "" });
        const bindings = bindSeries(slots, readings, dataset.series, getSnapshot().chosen);
        const run = await dojoApi.createRun({
          dataset_id: dataset.id, definition, bindings,
          name: `${name.trim() || "Unnamed service"} · ${formatInstant(Date.now())}`.slice(0, 120),
        });
        const { current, previous } = getSnapshot();
        // A new test has observations of its own; its latest is shown first.
        // It compares only with a test that read the same series.
        update({ ...getSnapshot(), step: undefined, observation: undefined,
          current: { run, definition, bindings, dataset: { id: dataset.id, name: dataset.name, ...boundSpan(dataset, bindings) } },
          previous: [scored(current), previous].find((item) => item?.dataset.id === dataset.id && sameBindings(item.bindings, bindings)) });
      } catch (reason) {
        update({ ...getSnapshot(), step: undefined, error: getErrorMessage(reason) });
      }
    },
    /** Take the test a design came with as this composer's test. One the member ran here stands over it. */
    adopt: async ({ run: id, by, definition }: DesignEvidence, signal: AbortSignal) => {
      const tested = () => !!getSnapshot().step || !!getSnapshot().current;
      if (!isCurrent() || tested()) return;
      try {
        const run = await dojoApi.run(id, signal);
        const [dataset, metrics] = await Promise.all([dojoApi.dataset(run.dataset_id, signal),
          run.status === "succeeded" ? dojoApi.metrics(id, signal) : undefined]);
        if (signal.aborted || tested()) return;
        // The next test runs on the same values and reads the same series, so the two compare.
        selection++;
        const bindings = Object.fromEntries(run.bindings.map((item) => [item.slot_id, item.series_id]));
        update({ ...getSnapshot(), choice: dataset.id, dataset, error: "", chosen: bindings,
          current: { run, metrics, definition, by, bindings,
            dataset: { id: dataset.id, name: dataset.name, ...boundSpan(dataset, bindings) } } });
      } catch (reason) {
        if (!signal.aborted && !tested())
          update({ ...getSnapshot(), error: `The test this design came with could not be opened. ${getErrorMessage(reason)}` });
      }
    },
    /** Follow the run in progress; its metrics are read as soon as it has finished. */
    refresh: async (signal: AbortSignal) => {
      const { current } = getSnapshot();
      if (!isCurrent() || !current || !isActive(current.run)) return;
      try {
        const run = await dojoApi.run(current.run.id, signal);
        const metrics = run.status === "succeeded" ? await dojoApi.metrics(run.id, signal) : undefined;
        if (signal.aborted || getSnapshot().current !== current) return;
        update({ ...getSnapshot(), current: { ...current, run, metrics }, error: "" });
      } catch (reason) {
        if (!signal.aborted && getSnapshot().current === current) update({ ...getSnapshot(), error: getErrorMessage(reason) });
      }
    },
    /** Metrics follow the dataset's labels, which may have changed in the Dojo meanwhile. */
    rescore: async (signal: AbortSignal) => {
      const { current, previous } = getSnapshot();
      const finished = [current, previous].filter((item): item is TestedRun => !!scored(item));
      if (!isCurrent() || !finished.length) return;
      try {
        const read = await Promise.all(finished.map((item) => dojoApi.metrics(item.run.id, signal)));
        const latest = getSnapshot();
        if (signal.aborted || latest.current !== current || latest.previous !== previous) return;
        const renewed = (item?: TestedRun) => {
          const index = item ? finished.indexOf(item) : -1;
          return index < 0 ? item : { ...item!, metrics: read[index] };
        };
        update({ ...latest, current: renewed(current), previous: renewed(previous) });
      } catch {
        // The figures already shown stay; the next test reads them again.
      }
    },
    watch: (watching: boolean) => {
      const { samples, ...rest } = getSnapshot();
      // Unfolding again tries values again that could not be read.
      if (rest.watching !== watching) update({ ...rest, watching, samples: samples?.error ? undefined : samples });
    },
    /** Read the values of the finished test once; they stay as the member moves from step to step. */
    sample: async () => {
      const { current, samples } = getSnapshot();
      if (!isCurrent() || !current?.metrics || samples?.run === current.run.id) return;
      const run = current.run.id;
      const settle = (read: Pick<NonNullable<Snapshot["samples"]>, "items" | "error">) => {
        if (getSnapshot().samples?.run === run) update({ ...getSnapshot(), samples: { run, ...read } });
      };
      update({ ...getSnapshot(), samples: { run } });
      try {
        settle({ items: (await dojoApi.steps(run)).samples });
      } catch (reason) {
        settle({ error: getErrorMessage(reason) });
      }
    },
    observe: (observation: number) => update({ ...getSnapshot(), observation }),
    cancel: async () => {
      const { current } = getSnapshot();
      if (!current || !isActive(current.run)) return;
      try {
        const run = await dojoApi.cancelRun(current.run.id);
        if (getSnapshot().current === current) update({ ...getSnapshot(), current: { ...current, run }, error: "" });
      } catch (reason) {
        update({ ...getSnapshot(), error: getErrorMessage(reason) });
      }
    },
  };
}

export type HistoryTest = ReturnType<typeof useHistoryTest>;

/** The tests of the composer with this key. */
export function useHistoryTest(key: string) {
  const session = navigationDraft(key, createHistoryTest);
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const running = !!snapshot.current && isActive(snapshot.current.run);
  return { ...snapshot, running, busy: running || !!snapshot.step, session };
}

/** Follows the run in progress. One owner per composer, mounted for as long as the composer is. */
export function useFollowTest({ session, current, running }: HistoryTest) {
  const runId = current?.run.id;
  const refresh = useCallback((signal: AbortSignal) => runId ? session.refresh(signal) : undefined, [runId, session]);
  usePollingLoop(refresh, { enabled: running, intervalMs: 1500, schedule: "after-completion",
    pauseWhenHidden: true, resumeOnVisible: true });
}

/** What a test is doing while it is under way, and how far it has read once it runs. */
export function testProgress(test: Pick<HistoryTest, "step" | "current">): { label: string; share?: number } | undefined {
  if (test.step === "copying") return { label: "Copying values…" };
  if (test.step === "starting") return { label: "Starting…" };
  const run = test.current?.run;
  if (!run || !isActive(run)) return undefined;
  if (run.cancel_requested) return { label: "Stopping…" };
  if (run.status === "queued") return { label: "Waiting…" };
  return { label: "Testing", share: run.points_total ? Math.floor((run.points_read / run.points_total) * 100) : 0 };
}

/** The same in a few words, for the button that opens the panel. */
export function testStatus(test: Pick<HistoryTest, "step" | "current">) {
  const progress = testProgress(test);
  return progress && (progress.share === undefined ? progress.label : `${progress.label} ${progress.share} %`);
}

export type TestFigure = { label: string; value: string; before?: string; help?: string };

const perDay = (value: number | null | undefined) =>
  value == null ? "" : ` · ${(value >= 10 ? Math.round(value) : Math.round(value * 100) / 100).toLocaleString()} per day`;

function figures(metrics: RunMetrics): TestFigure[] {
  const alarms = `${metrics.false_alarms.toLocaleString()}${perDay(metrics.false_alarms_per_day)}`;
  const once = "Observations that alarm one after the other count as one alarm.";
  if (!metrics.labels_total) return [{ label: "Alarms", value: alarms, help: once }];
  return [
    { label: "Labels detected", value: `${metrics.labels_detected} of ${metrics.labels_scored}` },
    { label: "Median delay", value: formatDuration(metrics.median_delay_seconds) },
    { label: "False alarms", value: alarms, help: `Alarms outside every label. ${once}` },
  ];
}

/** What a finished test found, each figure beside the one of the test before it. */
export function testFigures(current: RunMetrics, previous?: RunMetrics): TestFigure[] {
  const earlier = new Map(previous ? figures(previous).map((item) => [item.label, item.value]) : []);
  return figures(current).map((item) => {
    const before = earlier.get(item.label);
    return before === undefined || before === item.value ? item : { ...item, before };
  });
}

/** How long the design learned before its first score, and how long it was scored after that. */
export function testSpans(tested: Pick<TestedRun, "dataset">, metrics: Pick<RunMetrics, "scored_from" | "scored_to">) {
  const start = tested.dataset.start_at ? Date.parse(tested.dataset.start_at) : undefined;
  const end = tested.dataset.end_at ? Date.parse(tested.dataset.end_at) : undefined;
  if (start === undefined || end === undefined || !(end > start)) return undefined;
  const from = metrics.scored_from ? Date.parse(metrics.scored_from) : undefined;
  const to = metrics.scored_to ? Date.parse(metrics.scored_to) : undefined;
  return { start, end, from, to,
    learning: from === undefined ? end - start : Math.max(0, from - start),
    scoring: from === undefined || to === undefined ? 0 : Math.max(0, to - from) };
}

/** A moment of the tested values without its year: they lie days or weeks back, not years. */
export const shortInstant = (time: number | string) => new Intl.DateTimeFormat(undefined,
  { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(time));

/** How many stretches of time a test is summed up in to be drawn: one per half percent of its span. */
export const TEST_STRETCHES = 200;

const share = (spans: { start: number; end: number }, time: number) =>
  Math.min(100, Math.max(0, ((time - spans.start) / (spans.end - spans.start)) * 100));
const hundredths = (value: number) => Math.round(value * 100) / 100;
/** A score or a p-value in a few characters, whatever its size. */
const figure = (value: number) => value !== 0 && Math.abs(value) < 0.001
  ? value.toExponential(1).replace(".0e", "e")
  : value.toLocaleString(undefined, { maximumSignificantDigits: 3, notation: "compact" });

/** Where on the span of the values the design alarmed, in percent: one place per stretch of time. */
export function alarmMarks(outline: RunOutline, spans: { start: number; end: number }) {
  const half = outline.bucket_seconds * 500;
  return [...new Set(outline.buckets.filter((bucket) => bucket.alarms > 0)
    .map((bucket) => Math.round(share(spans, Date.parse(bucket.start_at) + half) * 2) / 2))];
}

export type RuleShape = {
  /** A p-value is drawn rarer upward; a score as it is, against the boundary it alarms above. */
  kind: "p" | "score";
  /** Paths on a field of 100 by 100: the scores of every stretch, of those that alarmed, and the boundary. */
  scores: string;
  alarmed: string;
  boundary: string;
  /** What the upper and the lower edge of the field stand for. */
  top: string;
  bottom: string;
  summary: string;
};

/** The detection rule over the span of the values: what each stretch of time scored, against its boundary.
 *
 * Every stretch is a bar from its lowest to its highest score, so no peak is lost to thinning. A design
 * that alarms on conformal p-values has no boundary to draw: its alarm follows a run of rare values.
 */
export function ruleShape(outline: RunOutline, spans: { start: number; end: number }): RuleShape | undefined {
  const rare = outline.strategy === "static_baseline";
  // A p-value stands as high as it is rare, so up means unusual for either kind of result.
  const level = (value: number) => rare ? -Math.log10(Math.min(1, Math.max(value, 1e-12))) : value;
  const stretches = outline.buckets.flatMap((bucket) => {
    if (bucket.score_min === null || bucket.score_max === null) return [];
    const ends = [level(bucket.score_min), level(bucket.score_max)];
    return [{ at: Date.parse(bucket.start_at), low: Math.min(...ends), high: Math.max(...ends), alarmed: bucket.alarms > 0,
      boundary: rare || bucket.threshold_min === null || bucket.threshold_max === null
        ? undefined : (bucket.threshold_min + bucket.threshold_max) / 2 }];
  });
  if (!stretches.length) return undefined;
  const boundaries = stretches.flatMap((item) => item.boundary ?? []);
  const floor = rare ? 0 : Math.min(...stretches.map((item) => item.low), ...boundaries);
  const peak = Math.max(...stretches.map((item) => item.high), ...boundaries);
  // One outlying score must not flatten the rest: the boundary keeps a quarter of the height, and
  // p-values reach down to 0.01 at least, so an uneventful history does not look like an eventful one.
  const reach = boundaries.length ? Math.max(...boundaries) - floor : 0;
  const ceiling = rare ? Math.max(peak, 2) : reach > 0 ? Math.min(peak, floor + reach * 4) : peak;
  const range = ceiling - floor || 1;
  // The upper six percent stay free, so a boundary at the very top is still a whole line.
  const y = (value: number) => hundredths(100 - Math.min(1, Math.max(0, (value - floor) / range)) * 94);
  const width = hundredths(Math.max(((outline.bucket_seconds * 1000) / (spans.end - spans.start)) * 100, 0.5));
  const bars = { scores: "", alarmed: "" };
  let boundary = "";
  let edge: number | undefined;
  for (const item of stretches) {
    const x = hundredths(share(spans, item.at));
    const bottom = y(item.low);
    // A stretch whose scores agree is still a mark of its own.
    bars[item.alarmed ? "alarmed" : "scores"] += `M${x} ${Math.min(y(item.high), bottom - 1.5)}h${width}V${bottom}h${-width}z`;
    if (item.boundary === undefined) { edge = undefined; continue; }
    // The line steps on from the stretch before, and starts anew after a stretch without results.
    boundary += edge !== undefined && x - edge < width / 2 ? `V${y(item.boundary)}` : `M${x} ${y(item.boundary)}`;
    edge = hundredths(x + width);
    boundary += `H${edge}`;
  }
  const scores = outline.buckets.flatMap((bucket) => bucket.score_min === null || bucket.score_max === null
    ? [] : [bucket.score_min, bucket.score_max]);
  const limits = outline.buckets.flatMap((bucket) => bucket.threshold_min === null || bucket.threshold_max === null
    ? [] : [bucket.threshold_min, bucket.threshold_max]);
  const between = (values: number[]) => {
    const [low, high] = [figure(Math.min(...values)), figure(Math.max(...values))];
    return low === high ? `of ${low}` : `between ${low} and ${high}`;
  };
  return {
    kind: rare ? "p" : "score", ...bars, boundary,
    top: rare ? `p ${figure(10 ** -ceiling)}` : figure(ceiling),
    bottom: rare ? "p 1" : figure(floor),
    summary: rare ? `p-values ${between(scores)}; a lower one is a rarer value`
      : `Scores ${between(scores)}${boundaries.length ? `, against a boundary ${between(limits)}` : ""}`,
  };
}

/** A value of a step in a few digits: enough to tell two values apart, short enough for a narrow column. */
export const stepValue = (value: number | string) => typeof value === "string" ? value
  : value !== 0 && Math.abs(value) < 0.0001 ? value.toExponential(2)
    : value.toLocaleString(undefined, { maximumSignificantDigits: 5 });

type Named = Array<[string, number | string]>;

/** What one observation of a test looked like at a step: the values that went in and came out, in the
 * order they were kept, and in words why there are none. */
export type StepValues = {
  input?: Named;
  output?: Named;
  /** Why the step gave nothing for this observation. */
  note?: string;
  /** The calibration step's part is reported by the detection rule that runs it. */
  borrowed: boolean;
};

const named = (values: PipelineNodePreview["output"]): Named | undefined =>
  values === null ? undefined : typeof values === "number" ? [["value", values]] : Object.entries(values);

const IDLE: Record<string, string> = {
  initializing: "Still collecting values before its first output.",
  waiting_for_dependency: "Waiting for a step before it.",
  held_back: "Held back by a Gate.",
  rejected: "Skipped this observation.",
};

/** The values of one step in one sampled observation, or undefined where the test kept none for it. */
export function stepValues(sample: StepSample, node: string, definition: Pick<PipelineDefinition, "nodes">): StepValues | undefined {
  const kind = definition.nodes.find((item) => item.id === node)?.kind;
  const rule = kind === "calibration" && !sample.steps[node]
    ? definition.nodes.find((item) => item.kind === "policy")?.id : undefined;
  const step = sample.steps[rule ?? node];
  if (!step) return undefined;
  // A detection rule gives one number, which says whether it alarmed.
  const output = (rule || kind === "policy") && typeof step.output === "number"
    ? [["alarm", step.output ? "yes" : "no"]] satisfies Named : named(step.output);
  // An input passes its readings on as they are; they are shown once, as what it gives.
  const input = kind === "source" ? undefined : named(step.input);
  // The runtime's own words where they say more than the state; its note on a pass that did not run is internal.
  const note = output ? undefined
    : step.state === "not_executed" || !(step.state in IDLE)
      ? "Did not run for this observation: the design was still learning."
      : step.reason ? `${step.reason.replace(/\.$/, "")}.` : IDLE[step.state];
  return { input, output, note, borrowed: !!rule };
}
