/** Editor types shared by pure modules and components, so neither imports the other. */
import type { Node } from "@xyflow/react";
import type { PipelineNode } from "./contracts";
import type { DataKind } from "./semantics";

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

/** History entry: `true` records a step, `false` skips it, and a string merges
 * consecutive edits of the same field (typing) into one step. */
export type HistoryMode = boolean | string;
export type PlacementRequest = { id: string; request: number };
