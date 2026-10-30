import { CircleCheck, LoaderCircle, TriangleAlert } from "lucide-react";
import { applyFinished, type usePipelineApply } from "./applySession";

const phases: Record<string, string> = {
  requested: "Preparing your service…", preflighting: "Checking the configuration…",
  validated: "Configuration checked", retiring: "Stopping the previous service…",
  starting: "Starting monitoring…", awaiting_heartbeat: "Waiting for the service to connect…",
  succeeded: "Monitoring applied", cancelling: "Cancelling…", cancelled: "Setup cancelled", failed: "Monitoring could not start",
};

export function PipelineApplyStatus({ apply, onInspect }: {
  apply: ReturnType<typeof usePipelineApply>; onInspect?: (nodeId: string) => void;
}) {
  const { operation, request, error, busy, session } = apply;
  if (!request && !error) return null;
  const terminal = applyFinished(operation);
  const failed = operation?.phase === "failed" || !!error;
  return <section className={`pl-apply-status${failed ? " pl-apply-status--error" : ""}`} aria-label="Monitoring setup progress" aria-live="polite">
    <div className="pl-apply-status-heading">
      {failed ? <TriangleAlert size={18} /> : terminal ? <CircleCheck size={18} /> : <LoaderCircle className="pl-spin" size={18} />}
      <div><h3>{operation ? phases[operation.phase] : busy ? "Applying monitoring…" : request ? "Connection interrupted" : "Check your setup"}</h3>
        <p>{operation?.error ?? error ?? ""}</p>
        {!operation && request && !busy && <p>The response was interrupted. Retry the same request to safely recover its result.</p>}
      </div>
    </div>
    {!!operation?.issues?.length && <ul>{operation.issues.map((issue, index) => <li key={index}>
      {issue.node_id && onInspect
        ? <button type="button" onClick={() => onInspect(issue.node_id!)}>{issue.message}</button>
        : issue.message}
    </li>)}</ul>}
    <div className="pl-actions">
      {!operation && request && !busy && <button type="button" onClick={() => void session.submit()}>Recover start request</button>}
      {operation && !terminal && <button type="button" disabled={busy || operation.phase === "cancelling"}
        onClick={() => void session.cancel()}>Cancel start</button>}
      {terminal && operation?.phase !== "succeeded" && <button type="button" onClick={session.reset}>Return to setup</button>}
    </div>
    {request?.replace_service_id && operation?.phase === "failed" && <p>The previous service may have stopped. Check its status before trying again.</p>}
  </section>;
}
