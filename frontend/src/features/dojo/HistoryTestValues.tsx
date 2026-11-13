import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo } from "react";
import type { DesignTestValuesProps } from "../pipelines/designTest";
import { shortInstant, stepValue, stepValues, useHistoryTest, type HistoryTest, type StepValues } from "./historyTest";
import "./history-test.css";

function Values({ label, values, note }: { label: string; values?: StepValues["input"]; note?: string }) {
  return <div className="dj-step-side">
    <h5>{label}</h5>
    {values
      ? <dl>{values.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{stepValue(value)}</dd></div>)}</dl>
      : <p className="pl-help">{note}</p>}
  </div>;
}

/** One sampled observation of the finished test at this step. Mounted only while unfolded, so a test
 * whose values nobody looks at is not read. */
function Observation({ test, run, node, definition }: { test: HistoryTest; run: string } & Pick<DesignTestValuesProps, "node" | "definition">) {
  const { session } = test;
  const read = test.samples?.run === run ? test.samples : undefined;
  useEffect(() => { if (!read) void session.sample(); }, [read, session]);
  const { items: samples, error } = read ?? {};
  const tested = test.current?.definition;
  const stale = useMemo(() => !!tested && JSON.stringify(tested) !== JSON.stringify(definition), [tested, definition]);
  if (error) return <p className="pl-error" role="alert">The values could not be read. {error}</p>;
  if (!samples) return <p className="pl-help">Reading the values…</p>;
  // The latest observation first: the design has learned the most by then.
  const index = Math.min(test.observation ?? Infinity, samples.length - 1);
  const sample = samples[index];
  if (!sample) return <p className="pl-help">The last test gave no results, so it has no values to show.</p>;
  const values = stepValues(sample, node, definition);
  return <>
    <div className="dj-step-observation">
      <p className="pl-help" role="status">Observation {index + 1} of {samples.length} · {shortInstant(sample.timestamp)}</p>
      {samples.length > 1 && <div className="dj-step-move">
        <button type="button" aria-label="Earlier observation" title="Earlier observation" disabled={index === 0}
          onClick={() => test.session.observe(index - 1)}><ChevronLeft size={14} aria-hidden="true" /></button>
        <button type="button" aria-label="Later observation" title="Later observation" disabled={index === samples.length - 1}
          onClick={() => test.session.observe(index + 1)}><ChevronRight size={14} aria-hidden="true" /></button>
      </div>}
    </div>
    {stale && <p className="pl-help">The design has changed since this test.</p>}
    {!values ? <p className="pl-help">The last test has no values for this step. Test again to see them.</p> : <>
      {values.borrowed && <p className="pl-help">Calibration runs inside the detection rule, so these are the rule&apos;s values.</p>}
      {values.input && <Values label="In" values={values.input} />}
      {values.input || values.output ? <Values label="Out" values={values.output} note={values.note} />
        : <p className="pl-help">{values.note}</p>}
    </>}
  </>;
}

/** With a step's settings: what went into the step and what came out of it in the last test, one sampled
 * observation at a time. It stays folded until asked for, and then stays unfolded on the same observation
 * from step to step, so one set of readings can be followed through the design. */
export function HistoryTestValues({ session, node, definition, onOpenTest }: DesignTestValuesProps) {
  const test = useHistoryTest(session);
  const finished = test.current?.metrics ? test.current.run.id : undefined;
  return <details className="dj-step-values" open={!!test.watching}
    onToggle={(event) => test.session.watch(event.currentTarget.open)}>
    <summary>Values in the last test</summary>
    {!test.watching ? null
      : finished ? <Observation test={test} run={finished} node={node} definition={definition} />
        : <p className="pl-help">{test.busy
          ? "The test is running. The values that go into this step and come out of it appear here when it has finished."
          : <>Test the design on history to see the values that go into this step and come out of it.{" "}
            <button type="button" className="dj-test-inline" onClick={onOpenTest}>Open the test</button></>}</p>}
  </details>;
}
