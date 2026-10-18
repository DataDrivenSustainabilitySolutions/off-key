import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { CheckCircle2, Clock3, TriangleAlert } from "lucide-react";
import type { PipelineNode } from "./contracts";
import { dataKinds, nodeKinds, sampledState, type DataKind } from "./semantics";

export type CanvasData = {
  label: string;
  kind: PipelineNode["kind"];
  operation: string;
  available: boolean;
  inputPort: boolean;
  outputPort: boolean;
  inputType?: DataKind | null;
  outputType?: DataKind;
  /** Undefined at rest, null for a valid target, otherwise the rejection reason. */
  inputIssue?: string | null;
  outputIssue?: string | null;
  state?: string;
  issueCount: number;
  [key: string]: unknown;
};
export type CanvasNode = Node<CanvasData, "component">;

function ConnectionDot({ direction, kind, connectable, issue }: {
  direction: "input" | "output";
  kind?: DataKind | null;
  connectable: boolean;
  issue?: string | null;
}) {
  const label = `${direction === "input" ? "Input" : "Output"}: ${kind ? dataKinds[kind].label : "Unavailable type"}`;
  return <Handle
    id={direction}
    type={direction === "input" ? "target" : "source"}
    position={direction === "input" ? Position.Left : Position.Right}
    isConnectable={connectable}
    isConnectableStart={connectable}
    isConnectableEnd={connectable && !issue}
    className={`pl-data--${kind ?? "unknown"}${issue === null ? " is-compatible" : issue ? " is-incompatible" : ""}`}
    title={issue ? `${label}. ${issue}` : label}
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
        {nodeKinds[data.kind]}
      </span>
      <div className="pl-node-title">
        <strong title={data.label}>{data.label}</strong>
        {data.label !== data.operation && (
          <small className="pl-node-operation" title={data.operation}>
            {data.operation}
          </small>
        )}
      </div>
      {data.inputPort && <ConnectionDot direction="input" kind={data.inputType}
        connectable={isConnectable && data.available} issue={data.inputIssue} />}
      {data.outputPort && <ConnectionDot direction="output" kind={data.outputType}
        connectable={isConnectable && data.available} issue={data.outputIssue} />}
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
