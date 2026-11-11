import { useNow } from "@/hooks/use-now";
import { useState } from "react";
import { rejectionSummary, type NodePass, type PipelineState } from "./diagnostics";
import { PipelineLearningSummary } from "./PipelineLearningSummary";
export type { PipelineState } from "./diagnostics";

function Values({
  label,
  values,
}: {
  label: string;
  values: NodePass["output"];
}) {
  return (
    <div className="pl-sample">
      <strong>{label}</strong>
      {values === null ? (
        <span>No value captured</span>
      ) : typeof values === "number" ? (
        <span>{values.toPrecision(7)}</span>
      ) : (
        <dl>
          {Object.entries(values).map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{value.toPrecision(7)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const share = (value: number | null) => (value === null ? "Not captured" : String(Number(value.toPrecision(4))));

/** Each detector's score and surprise in the sampled observation, for a policy that
 * combines several. */
function ObservedDetectors({
  detectors,
  nodeLabels,
  onSelect,
}: {
  detectors: NonNullable<NonNullable<PipelineState["observation"]>["detectors"]>;
  nodeLabels?: Record<string, string>;
  onSelect?: (id: string) => void;
}) {
  return (
    <div className="pl-observed-detectors">
      <strong>Detectors in this observation</strong>
      <table>
        <thead>
          <tr><th scope="col">Detector</th><th scope="col">Score</th><th scope="col">Surprise</th></tr>
        </thead>
        <tbody>
          {detectors.map((item) => {
            const label = nodeLabels?.[item.detector_id] ?? item.detector_id;
            return (
              <tr key={item.detector_id}>
                <th scope="row">
                  {onSelect ? (
                    <button type="button" onClick={() => onSelect(item.detector_id)}>{label}</button>
                  ) : label}
                </th>
                <td>{item.score === null ? "Not captured" : item.score.toPrecision(7)}</td>
                <td>{share(item.surprise)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <small className="pl-help">
        A surprise is the share of that detector&apos;s calibration scores below its score.
        The policy combines the surprises, so detectors on different scales compare.
      </small>
    </div>
  );
}

export function PipelineDiagnostics({
  state,
  selected,
  expectedRunId,
  nodeLabels,
  policyId,
  calibrationId,
  onSelect,
}: {
  state?: PipelineState | null;
  selected?: string;
  expectedRunId?: string;
  nodeLabels?: Record<string, string>;
  /** The detection rule, which shows every detector's part when the design combines several. */
  policyId?: string;
  /** The calibration step. The runtime reports it together with the detection rule. */
  calibrationId?: string;
  onSelect?: (id: string) => void;
}) {
  const [pass, setPass] = useState<"score" | "learn">("score");
  const now = useNow(5_000);
  if (!state || (expectedRunId && state.run_id !== expectedRunId))
    return (
      <section
        className="pl-diagnostics"
        aria-label="Live component diagnostics"
      >
        <p>
          Waiting for a runtime snapshot. Legacy workers may not provide
          component diagnostics.
        </p>
      </section>
    );
  // A runtime that calibrates inside its detection rule reports both under the rule.
  const reported = selected && selected === calibrationId && !state.nodes[selected] ? policyId : selected;
  const node = reported ? state.nodes[reported] : undefined;
  const sample = reported
    ? state.observation?.passes[pass][reported]
    : undefined;
  const detectors = state.observation?.detectors;
  const observed = detectors?.find((item) => item.detector_id === selected);
  const age = Math.max(
    0,
    Math.floor((now - Date.parse(state.captured_at)) / 1000),
  );
  return (
    <section className="pl-diagnostics" aria-label="Live component diagnostics">
      <h3>Actual execution</h3>
      <p className="pl-help">
        Snapshot {Number.isFinite(age) ? `${age}s ago` : "time unavailable"} ·{" "}
        {state.phase.replace(/_/g, " ")} · observation {state.sequence_number}
      </p>
      {age > 15 && (
        <p role="status" className="pl-warning">
          Runtime snapshot is stale. Values below describe the last captured
          execution.
        </p>
      )}
      <PipelineLearningSummary state={state} />
      {!selected ? (
        <p>Select a component to inspect its execution.</p>
      ) : node ? (
        <>
          <dl className="pl-metrics">
            <div>
              <dt>State</dt>
              <dd>{node.state.replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Ready</dt>
              <dd>{node.ready ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Scoring calls</dt>
              <dd>{node.score_count}</dd>
            </div>
            <div>
              <dt>Learning calls</dt>
              <dd>{node.learn_count}</dd>
            </div>
            {node.learned_updates != null && (
              <div>
                <dt>Successful learning updates</dt>
                <dd>{node.learned_updates}</dd>
              </div>
            )}
            {(node.readiness_observed != null ||
              node.readiness_required != null) && (
              <div>
                <dt>Readiness progress</dt>
                <dd>
                  {node.readiness_observed ?? "Not reported"}
                  {node.readiness_required && node.readiness_required > 0
                    ? ` / ${node.readiness_required}`
                    : " · minimum not quantified"}
                </dd>
              </div>
            )}
            <div>
              <dt>Scoring time</dt>
              <dd>{(node.score_time_ns / 1_000_000).toFixed(3)} ms total</dd>
            </div>
            <div>
              <dt>Learning time</dt>
              <dd>{(node.learn_time_ns / 1_000_000).toFixed(3)} ms total</dd>
            </div>
          </dl>
          {node.learned_updates != null && (
            <p className="pl-help">
              Successful updates include restored history. Call counts cover the
              current diagnostics session.
            </p>
          )}
          {node.readiness_reason && (
            <p className="pl-help">{node.readiness_reason}</p>
          )}
          {rejectionSummary(node.rejections) && (
            <p className="pl-warning" role="status">
              {rejectionSummary(node.rejections)} Skipped observations change
              no state and count as coverage gaps.
            </p>
          )}
          {!!node.blocked_by?.length && (
            <div className="pl-actions">
              <span>Waiting on</span>
              {node.blocked_by.map((id) =>
                onSelect ? (
                  <button
                    type="button"
                    key={id}
                    aria-label={`Inspect prerequisite ${nodeLabels?.[id] ?? id}`}
                    onClick={() => onSelect(id)}
                  >
                    {nodeLabels?.[id] ?? id}
                  </button>
                ) : (
                  <span key={id}>{nodeLabels?.[id] ?? id}</span>
                ),
              )}
            </div>
          )}
          {node.error && (
            <p role="alert" className="pl-error">
              {node.error}
            </p>
          )}
        </>
      ) : (
        <p>This component has not reported execution statistics.</p>
      )}
      {state.observation && (
        <>
          <p className="pl-help">
            Sampled observation {state.observation.sequence_number} at{" "}
            <time>{state.observation.timestamp}</time>. These bounded previews
            come from actual execution and do not rerun the pipeline.
          </p>
          <div className="pl-switch" aria-label="Execution pass">
            <button
              type="button"
              aria-pressed={pass === "score"}
              onClick={() => setPass("score")}
            >
              Before learning
            </button>
            <button
              type="button"
              aria-pressed={pass === "learn"}
              onClick={() => setPass("learn")}
            >
              Learning pass
            </button>
          </div>
          {pass === "score" && detectors?.length && reported === policyId ? (
            <ObservedDetectors detectors={detectors} nodeLabels={nodeLabels} onSelect={onSelect} />
          ) : null}
          {sample ? (
            <>
              <p>
                {sample.state.replace(/_/g, " ")}
                {sample.reason ? ` · ${sample.reason}` : ""}
              </p>
              <Values label="Input" values={sample.input} />
              <Values label="Output" values={sample.output} />
              {pass === "score" && observed && (
                <p className="pl-help">
                  Surprise {share(observed.surprise)}: the share of this detector&apos;s
                  calibration scores below its score.
                </p>
              )}
            </>
          ) : (
            selected && (
              <p>No sample for this component in the selected pass.</p>
            )
          )}
          {state.truncated && (
            <p className="pl-help">
              Preview truncated to the configured size limit.
            </p>
          )}
          <details>
            <summary>Original input timestamps</summary>
            <dl className="pl-metrics">
              {Object.entries(state.observation.input_timestamps).map(
                ([id, timestamp]) => (
                  <div key={id}>
                    <dt>{id}</dt>
                    <dd>{timestamp}</dd>
                  </div>
                ),
              )}
            </dl>
          </details>
        </>
      )}
      {state.diagnostic_errors > 0 && (
        <p className="pl-help">
          {state.diagnostic_errors} diagnostics capture errors. Monitoring
          results are independent of diagnostics.
        </p>
      )}
    </section>
  );
}
