/** Editor types shared by pure modules and components, so neither imports the other. */
import type { Node } from "@xyflow/react";
import type { PipelineNode } from "./contracts";
import type { DataKind } from "./semantics";

type CanvasData = {
  label: string;
  kind: PipelineNode["kind"];
  /** What the step does, as the add-step menu groups it. */
  family: string;
  operation: string;
  available: boolean;
  inputPort: boolean;
  outputPort: boolean;
  inputType?: DataKind | null;
  outputType?: DataKind;
  /** Undefined at rest, null for a valid target, otherwise the rejection reason. */
  inputIssue?: string | null;
  outputIssue?: string | null;
  /** A compatible input that is taken: the component whose connection a drop replaces. */
  inputReplaces?: string;
  /** Feature columns leaving the output, with their names, once the compiler reported them. */
  outputCount?: number;
  outputFeatures?: string[];
  /** The count predates the latest edit and is being checked again. */
  outputStale?: boolean;
  state?: string;
  issueCount: number;
  /** Warnings never block applying the design. */
  warningCount?: number;
  /** One line about the settings, or the features a selection keeps. */
  summary?: string;
  chips?: string[];
  /** The title is being typed on the card. */
  renaming?: boolean;
  [key: string]: unknown;
};
export type CanvasNode = Node<CanvasData, "component">;

/** History entry: `true` records a step, `false` skips it, and a string merges
 * consecutive edits of the same field (typing) into one step. */
export type HistoryMode = boolean | string;
export type PlacementRequest = { id: string; request: number };
