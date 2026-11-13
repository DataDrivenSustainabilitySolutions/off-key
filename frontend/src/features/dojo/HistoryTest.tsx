import { useEffect, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";
import { Link } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type { DatasetSummary, LabelOutcome, RunOutline } from "@/types/dojo.generated";
import type { DesignTestProps, DesignTestStatusProps } from "../pipelines/designTest";
import { dojoApi } from "./api";
import { useRunOutline } from "./hooks";
import { formatDuration, formatInstant, formatSpan, isActive } from "./model";
import {
  alarmMarks, bindSeries, ruleShape, seriesComplete, shortInstant, TEST_STRETCHES, TEST_WINDOWS, testFigures, testProgress,
  testSpans, testStatus, useFollowTest, useHistoryTest, type RuleShape, type TestedRun,
} from "./historyTest";
import "./history-test.css";

type Spans = NonNullable<ReturnType<typeof testSpans>>;

/** The detection rule under the strip, on the same span of time: what every stretch scored, the
 * stretches that alarmed in the foreground colour, and the boundary as a line. */
function RuleChart({ shape }: { shape: RuleShape }) {
  return <div className="dj-test-rule" role="img" aria-label={shape.summary} title={shape.summary}>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path className="dj-test-scores" d={shape.scores} />
      <path className="dj-test-alarmed" d={shape.alarmed} />
      {shape.boundary && <path className="dj-test-boundary" d={shape.boundary} />}
    </svg>
    <span aria-hidden="true">{shape.top}</span><span aria-hidden="true">{shape.bottom}</span>
  </div>;
}

/** When the design alarmed, over the whole span of the values: learning first, then every alarm and label,
 * and under them what the design scored. Alarms and scores come with the outline, once it is read. */
function AlarmStrip({ spans, outline, labels }: { spans: Spans; outline?: RunOutline; labels: LabelOutcome[] }) {
  const share = (time: number) => Math.min(100, Math.max(0, ((time - spans.start) / (spans.end - spans.start)) * 100));
  const marks = useMemo(() => outline ? alarmMarks(outline, spans) : [], [outline, spans]);
  const shape = useMemo(() => outline && ruleShape(outline, spans), [outline, spans]);
  const learning = share(spans.start + spans.learning);
  return <>
    <div className="dj-test-strip" role="img" aria-label={`${
      !outline ? "Learning and labels" : marks.length ? "Alarms" : "No alarms"} between ${
      formatInstant(spans.start)} and ${formatInstant(spans.end)}`}>
      {learning > 0 && <span className="dj-test-learning" style={{ width: `${learning}%` }} />}
      {labels.map((label) => {
        const left = share(Date.parse(label.start_at));
        return <span key={label.label_id} className={`dj-test-label is-${label.outcome}`}
          style={{ left: `${left}%`, width: `${Math.max(share(Date.parse(label.end_at)) - left, 0.75)}%` }} />;
      })}
      {marks.map((mark) => <i key={mark} style={{ left: `${mark}%` }} />)}
    </div>
    {shape && <RuleChart shape={shape} />}
    <div className="dj-test-axis" aria-hidden="true">
      <span>{shortInstant(spans.start)}</span><span>{shortInstant(spans.end)}</span>
    </div>
    <ul className="dj-test-legend" aria-hidden="true">
      {learning > 0 && <li className="is-learning">Learning</li>}
      <li className="is-alarm">Alarm</li>
      {labels.length > 0 && <li className="is-label">Label</li>}
      {shape && <li className="is-score">{shape.kind === "p" ? "p-value, rarer upward" : "Score"}</li>}
      {shape?.boundary && <li className="is-boundary">Boundary</li>}
    </ul>
  </>;
}

function Result({ tested, previous, stale }: { tested: TestedRun; previous?: TestedRun; stale: boolean }) {
  const { run, metrics, dataset } = tested;
  const { outline, error } = useRunOutline(metrics ? run.id : undefined, TEST_STRETCHES);
  // The same spans for as long as the result stands, so the drawing is laid out once.
  const spans = useMemo(() => metrics && testSpans(tested, metrics), [tested, metrics]);
  if (run.status === "failed") return <p className="pl-error" role="alert">The test stopped. {run.error}</p>;
  if (run.status === "cancelled") return <p className="pl-help" role="status">The test was cancelled.</p>;
  if (!metrics) return null;
  const unscored = !metrics.scored_from;
  const dojo = `/dojo?dataset=${encodeURIComponent(dataset.id)}`;
  return <section className="dj-test-result" aria-label="Test result">
    <div className="dj-test-heading">
      <h4>Result</h4>
      <span>{dataset.name}</span>
    </div>
    {tested.by && <p className="pl-help">Tested by {tested.by}.</p>}
    {stale && <p className="pl-help" role="status">The design has changed since this test.</p>}
    {spans && <AlarmStrip spans={spans} outline={outline} labels={metrics.labels} />}
    {error && <p className="pl-error" role="alert">The alarms and scores could not be drawn. {error}</p>}
    <dl className="dj-test-figures">
      {!unscored && testFigures(metrics, previous?.metrics).map((item) => <div key={item.label}>
        <dt title={item.help}>{item.label}</dt>
        <dd>{item.value}{item.before !== undefined && <small>before {item.before}</small>}</dd>
      </div>)}
      {spans && <div><dt>Learning</dt><dd>{formatDuration(spans.learning / 1000)}</dd></div>}
      {spans && !unscored && <div><dt>Scored</dt><dd>{formatDuration(spans.scoring / 1000)}</dd></div>}
    </dl>
    {unscored ? <p className="pl-help">The design was still learning when the values ended, so nothing was scored.
      Test on a longer window, or shorten the learning in the service settings.</p>
      : !metrics.labels_total && <p className="pl-help">These values have no labels yet. Mark the known faults in the Dojo
        to see how many of them the design detects, and how fast.</p>}
    <Link className="dj-test-link" to={metrics.labels_total ? `${dojo}&tab=compare` : dojo}>
      {metrics.labels_total ? "Compare runs in the Dojo" : "Open in the Dojo"}</Link>
  </section>;
}

/** What the composer's button for the test shows. It is mounted for as long as the composer is, so it
 * follows a run while the panel is closed and says when one has ended there. The word stays as it is and
 * a line along the button's lower edge fills, so the toolbar does not move while a test counts. */
export function HistoryTestStatus({ session, open, evidence }: DesignTestStatusProps) {
  const test = useHistoryTest(session);
  useFollowTest(test);
  const store = test.session;
  useEffect(() => {
    if (!evidence) return;
    const controller = new AbortController();
    void store.adopt(evidence, controller.signal);
    return () => controller.abort();
  }, [store, evidence]);
  const ended = test.current && !isActive(test.current.run) ? test.current.run : undefined;
  // A test the design came with ended before the composer opened: there is nothing to announce.
  const silent = open || !!test.current?.by;
  const announced = useRef(ended?.id);
  useEffect(() => {
    if (!ended || announced.current === ended.id) return;
    announced.current = ended.id;
    if (silent) return;
    if (ended.status === "succeeded") toast.success("The test on history has finished.", { id: "history-test" });
    else if (ended.status === "failed") toast.error("The test on history stopped.", { id: "history-test" });
  }, [ended, silent]);
  const progress = testProgress(test);
  return <>Test <span className="ex-sr-only">on history{progress ? `, ${testStatus(test)!.toLowerCase()}` : ""}</span>
    {progress && <span className={`dj-test-meter${progress.share === undefined ? " is-waiting" : ""}`} aria-hidden="true"
      style={{ width: `${progress.share ?? 100}%` }} />}</>;
}

/** Runs the design in the composer over recorded values and shows what it would have reported. */
export function HistoryTestPanel({ session: key, definition, readings, name, scope, blocked, onChooseReadings }: DesignTestProps) {
  const test = useHistoryTest(key);
  const { session, current, choice, dataset, chosen } = test;
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [listError, setListError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    dojoApi.datasets({ limit: 100 }, controller.signal)
      .then((page) => { if (!controller.signal.aborted) setDatasets(page.items); })
      .catch((reason) => { if (!controller.signal.aborted) setListError(getErrorMessage(reason)); });
    // Labels set in the Dojo since the panel was last open change what the same alarms mean.
    void session.rescore(controller.signal);
    return () => controller.abort();
  }, [session]);
  // A copy made for a test is listed at once, before the list is read again.
  const listed = dataset && !datasets.some((item) => item.id === dataset.id) ? [dataset, ...datasets] : datasets;
  const slots = definition.input_slots;
  const copies = TEST_WINDOWS.some((item) => item.id === choice);
  const bindings = useMemo(() => dataset ? bindSeries(slots, readings, dataset.series, chosen) : {},
    [dataset, slots, readings, chosen]);
  // A copy holds one series per reading; only other values ask which series feeds which input.
  const matched = !!dataset && slots.every((slot) => !!readings[slot.id]
    && dataset.series.find((item) => item.id === bindings[slot.id])?.reading_id === readings[slot.id]);
  const unread = slots.length === 0 || slots.some((slot) => !readings[slot.id]);
  const reason = blocked
    ?? (copies
      ? unread ? "Choose a reading for every input first." : undefined
      : !dataset ? "" : seriesComplete(slots, bindings) ? undefined : "Choose a different series for each input.");
  const stale = useMemo(() => !!current && JSON.stringify(current.definition) !== JSON.stringify(definition),
    [current, definition]);
  const progress = testProgress(test);
  const run = current?.run;
  return <div className="dj-test">
    <p className="pl-help">Runs this design over recorded values in time order, as a live service would.
      Nothing reaches Monitoring or Reporting.</p>
    <label className="pl-field"><span>Values</span>
      <select value={choice} disabled={test.busy} onChange={(event) => void session.choose(event.target.value)}>
        <optgroup label="Recorded by the chosen readings">
          {TEST_WINDOWS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </optgroup>
        {listed.length > 0 && <optgroup label="Dojo datasets">
          {listed.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </optgroup>}
      </select>
    </label>
    <p className="pl-help">{copies
      ? "The values are copied into a Dojo dataset first. Later tests run on that copy, so their results compare."
      : dataset ? `${formatSpan(dataset.start_at, dataset.end_at)} · ${dataset.point_count.toLocaleString()} values`
        : test.error ? "" : "Loading the dataset…"}</p>
    {dataset && !matched && <fieldset className="dj-test-inputs"><legend>Inputs</legend>
      {slots.map((slot) => <label key={slot.id} className="pl-field">
        <span>{slot.label}{slot.unit ? ` (${slot.unit})` : ""}</span>
        <select value={bindings[slot.id] ?? ""} disabled={test.busy} aria-label={`Series for ${slot.label}`}
          onChange={(event) => session.bind(slot.id, event.target.value)}>
          <option value="" disabled>Choose a series</option>
          {dataset.series.map((item) => <option key={item.id} value={item.id}>
            {item.name}{item.unit ? ` (${item.unit})` : ""}</option>)}
        </select>
      </label>)}
    </fieldset>}
    {listError && <p className="pl-error" role="alert">The Dojo datasets could not be listed. {listError}</p>}
    {test.error && <p className="pl-error" role="alert">{test.error}</p>}
    {progress
      ? <div className="dj-test-progress">
        {/* The words are announced when they change; the share is read from the bar, not every second. */}
        <p><span role="status">{progress.label}</span>
          {progress.share !== undefined && <span aria-hidden="true"> {progress.share} %</span>}</p>
        {run && isActive(run) && <>
          <div className="dj-test-bar" role="progressbar" aria-label="Test progress" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={progress.share ?? 0}><span style={{ width: `${progress.share ?? 0}%` }} /></div>
          <button type="button" disabled={run.cancel_requested} onClick={() => void session.cancel()}>Cancel</button>
        </>}
      </div>
      : <div className="dj-test-actions">
        <button type="button" disabled={reason !== undefined}
          onClick={() => void session.start({ definition, readings, name, scope })}>
          {current ? "Test again" : "Run test"}</button>
        {reason && <p className="pl-help" role="status">{reason}
          {copies && unread && !blocked && onChooseReadings && <> <button type="button" className="dj-test-inline"
            onClick={onChooseReadings}>Choose readings</button></>}</p>}
      </div>}
    {current && !progress && <Result tested={current} previous={test.previous} stale={stale} />}
  </div>;
}
