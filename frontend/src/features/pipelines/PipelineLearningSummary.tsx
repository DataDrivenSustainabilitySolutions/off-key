import type { PipelineState } from "./diagnostics";

/** Global phase progress uses runtime history; sampled node calls are separate. */
export function PipelineLearningSummary({ state }: { state: PipelineState }) {
  const adaptive = state.adaptive_learning;
  const batch = state.batch_training;
  return (
    <>
      {adaptive && (
        <section aria-label="Adaptive learning progress">
          <h4>Adaptive learning</h4>
          <dl className="pl-metrics">
            <div>
              <dt>Learning phase</dt>
              <dd>{adaptive.state.replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Total detector updates</dt>
              <dd>{adaptive.model_updates}</dd>
            </div>
            <div>
              <dt>Warmup detector updates</dt>
              <dd>
                {adaptive.warmup_updates} / {adaptive.warmup_required}
              </dd>
            </div>
            <div>
              <dt>Graph ready</dt>
              <dd>{adaptive.ready ? "Yes" : "No"}</dd>
            </div>
          </dl>
          <p className="pl-help">
            Warmup also requires a ready learned reference. Detector updates
            include restored history.
          </p>
          {adaptive.reason && <p className="pl-help">{adaptive.reason}</p>}
        </section>
      )}
      {batch && (
        <section aria-label="Static fitting progress">
          <h4>Static fitting</h4>
          <dl className="pl-metrics">
            <div>
              <dt>Fitting phase</dt>
              <dd>{batch.state.replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Buffered training samples</dt>
              <dd>{batch.training_samples}</dd>
            </div>
            <div>
              <dt>Buffered calibration samples</dt>
              <dd>{batch.calibration_samples}</dd>
            </div>
            <div>
              <dt>Fitted baseline frozen</dt>
              <dd>{batch.frozen ? "Yes" : "No"}</dd>
            </div>
          </dl>
          <p className="pl-help">
            Counts describe current collection buffers and can reset after
            fitting.
          </p>
        </section>
      )}
    </>
  );
}
