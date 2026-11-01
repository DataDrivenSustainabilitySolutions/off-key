import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CheckCircle2, Clock3, TriangleAlert } from "lucide-react";
import { dataKinds, sampledState, type DataKind } from "./semantics";
import type { CanvasNode } from "./types";

/** Chips beyond these collapse into a count; the inspector lists every feature. */
const MAX_CHIPS = 3;
/** Feature names a port's tooltip lists before it summarizes the rest. */
const MAX_NAMES = 6;

function emittedFeatures(names: string[]) {
  const shown = names.slice(0, MAX_NAMES).join(", ");
  const rest = names.length > MAX_NAMES ? ` and ${names.length - MAX_NAMES} more` : "";
  return `${names.length} ${names.length === 1 ? "feature" : "features"}${shown ? `: ${shown}${rest}` : ""}`;
}

function ConnectionDot({ direction, kind, connectable, issue, replaces, count, features, stale }: {
  direction: "input" | "output";
  kind?: DataKind | null;
  connectable: boolean;
  issue?: string | null;
  replaces?: string;
  count?: number;
  features?: string[];
  stale?: boolean;
}) {
  const label = `${direction === "input" ? "Input" : "Output"}: ${kind ? dataKinds[kind].label : "Unavailable type"}`;
  const detail = issue ? issue
    : replaces ? `Replaces the connection from ${replaces}.`
      : features ? `${emittedFeatures(features)}.` : undefined;
  return <Handle
    id={direction}
    type={direction === "input" ? "target" : "source"}
    position={direction === "input" ? Position.Left : Position.Right}
    isConnectable={connectable}
    isConnectableStart={connectable}
    isConnectableEnd={connectable && !issue}
    className={`pl-data--${kind ?? "unknown"}${issue === null ? " is-compatible" : issue ? " is-incompatible" : ""}${
      count !== undefined ? " has-count" : ""}${stale ? " is-stale" : ""}`}
    data-count={count}
    title={detail ? `${label}. ${detail}` : label}
    role="img"
    aria-label={label}
  />;
}

export function PipelineNodeCard({
  data,
  selected,
  isConnectable,
}: NodeProps<CanvasNode>) {
  const status = data.state ? sampledState(data.state) : undefined;
  const StatusIcon =
    status?.tone === "failed"
      ? TriangleAlert
      : status?.tone === "ready"
        ? CheckCircle2
        : Clock3;
  return (
    <div
      className={`pl-node${selected ? " is-selected" : ""}`}
      data-kind={data.kind}
      onClick={(event) => {
        // A dot tap connects; only the card body opens component settings.
        if ((event.target as Element).closest(".react-flow__handle")) event.stopPropagation();
      }}
    >
      <span className="pl-node-kind">
        {data.family}
      </span>
      <div className="pl-node-title">
        <strong title={data.label}>{data.label}</strong>
        {data.label !== data.operation && (
          <small className="pl-node-operation" title={data.operation}>
            {data.operation}
          </small>
        )}
        {data.summary && (
          <small className="pl-node-summary" title={data.summary}>
            {data.summary}
          </small>
        )}
        {!!data.chips?.length && (
          <span className="pl-node-chips" title={data.chips.join(", ")}>
            {data.chips.slice(0, MAX_CHIPS).map((chip, index) => <span key={index}>{chip}</span>)}
            {data.chips.length > MAX_CHIPS && <span className="is-more">+{data.chips.length - MAX_CHIPS}</span>}
          </span>
        )}
      </div>
      {data.inputPort && <ConnectionDot direction="input" kind={data.inputType}
        connectable={isConnectable && data.available} issue={data.inputIssue} replaces={data.inputReplaces} />}
      {data.outputPort && <ConnectionDot direction="output" kind={data.outputType}
        connectable={isConnectable && data.available} issue={data.outputIssue}
        count={data.outputCount} features={data.outputFeatures} stale={data.outputStale} />}
      <div className="pl-node-status">
        {!data.available && (
          <span className="pl-node-issue">
            <TriangleAlert size={11} aria-hidden="true" />
            Unavailable component
          </span>
        )}
        {data.issueCount > 0 && (
          <span
            className="pl-node-issue"
            title="Configuration issues. Select the component for details."
          >
            <TriangleAlert size={11} aria-hidden="true" />
            {data.issueCount} {data.issueCount === 1 ? "issue" : "issues"}
          </span>
        )}
        {status && (
          <span
            className={`pl-node-sample pl-node-sample--${status.tone}`}
            title={`Reported runtime state: ${status.label}`}
          >
            <StatusIcon size={11} aria-hidden="true" />
            {status.label}
          </span>
        )}
      </div>
    </div>
  );
}
