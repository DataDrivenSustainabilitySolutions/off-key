/** Editor types shared by pure modules and components, so neither imports the other. */
import type { Node } from "@xyflow/react";
import type { PipelineNode } from "./contracts";
import type { StepChange } from "./comparison";
import type { DataKind } from "./semantics";

type CanvasData = {
  label: string;
  kind: PipelineNode["kind"];
  /** What the step does, as the add-step menu groups it. */
  family: string;
  /** How a learned step learns: "Fitted once", "Learns continuously" or "Pretrained". */
  learning?: string;
  operation: string;
  /** The step is switched off: its features pass through, and the card keeps what it was. */
  off?: boolean;
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
  /** What the step still lacks while the design is built, such as "Not connected yet". */
  open?: string;
  /** One line about the settings, or the features a selection keeps. */
  summary?: string;
  chips?: string[];
  /** The title is being typed on the card. */
  renaming?: boolean;
  /** How the step differs from the design a service runs now, where the canvas is compared with one. */
  change?: StepChange;
  [key: string]: unknown;
};
export type CanvasNode = Node<CanvasData, "component">;

/** History entry: `true` records a step, `false` skips it, and a string merges
 * consecutive edits of the same field (typing) into one step. */
export type HistoryMode = boolean | string;
export type PlacementRequest = { id: string; request: number };
