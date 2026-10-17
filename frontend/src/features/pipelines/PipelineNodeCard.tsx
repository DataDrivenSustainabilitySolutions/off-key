import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  Bell,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Database,
  GitMerge,
  RadioReceiver,
  SlidersHorizontal,
  TriangleAlert,
} from "lucide-react";
import type { PipelineNode } from "./contracts";
import { dataKinds, nodeKinds, sampledState, type DataKind } from "./semantics";

export type CanvasData = {
  label: string;
  kind: PipelineNode["kind"];
  operation: string;
  description: string;
  available: boolean;
  inputPort: boolean;
  outputPort: boolean;
  inputType?: DataKind | null;
  outputType?: DataKind;
  state?: string;
  issueCount: number;
  [key: string]: unknown;
};
export type CanvasNode = Node<CanvasData, "component">;

const roleIcons = {
  source: RadioReceiver,
  transform: SlidersHorizontal,
  merge: GitMerge,
  detector: BrainCircuit,
  policy: Bell,
  output: Database,
};

export function PipelineNodeCard({
  data,
  selected,
  isConnectable,
}: NodeProps<CanvasNode>) {
  const Icon = roleIcons[data.kind];
  const status = data.state ? sampledState(data.state) : undefined;
  const StatusIcon =
    status?.tone === "failed"
      ? TriangleAlert
      : status?.tone === "ready"
        ? CheckCircle2
        : Clock3;
  const subtitle =
    data.label !== data.operation ? data.operation : data.description;
  return (
    <div
      className={`pl-node${selected ? " is-selected" : ""}`}
      data-kind={data.kind}
    >
      {data.inputPort && (
        <Handle
          id="input"
          type="target"
          position={Position.Left}
          isConnectable={isConnectable && data.available}
          className={`pl-data--${data.inputType ?? "unknown"}`}
          title={`Input: ${data.inputType ? dataKinds[data.inputType].label : "Unavailable type"}`}
        />
      )}
      <span className="pl-node-kind">
        <Icon size={12} aria-hidden="true" />
        {nodeKinds[data.kind]}
      </span>
      <strong title={data.label}>{data.label}</strong>
      <small className="pl-node-operation" title={subtitle}>
        {subtitle}
      </small>
      <div className="pl-node-ports">
        {data.inputPort ? (
          <span className={`pl-port pl-data--${data.inputType ?? "unknown"}`}>
            In · {data.inputType ? dataKinds[data.inputType].label : "Unknown"}
          </span>
        ) : (
          <span />
        )}
        {data.outputPort ? (
          <span className={`pl-port pl-data--${data.outputType ?? "unknown"}`}>
            Out ·{" "}
            {data.outputType ? dataKinds[data.outputType].label : "Unknown"}
          </span>
        ) : data.kind === "output" && data.available ? (
          <span className="pl-port">Stores evidence</span>
        ) : null}
      </div>
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
      {data.outputPort && (
        <Handle
          id="output"
          type="source"
          position={Position.Right}
          isConnectable={isConnectable && data.available}
          className={`pl-data--${data.outputType ?? "unknown"}`}
          title={`Output: ${data.outputType ? dataKinds[data.outputType].label : "Unavailable type"}`}
        />
      )}
    </div>
  );
}
