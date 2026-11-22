import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineDefinition,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { nodeSummary } from "@/features/pipelines/summaries";

export const stepNode = (component: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: component.id, params });

/** A design with one reading and no steps, for a step's summary. */
export const oneReading: PipelineDefinition = normalizeDefinition({
  input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [],
});

export const stepSummary = (
  component: PipelineComponent, params?: PipelineNode["params"], definition = oneReading,
) => nodeSummary(stepNode(component, params), component, definition);

/** A compiler issue as the step panels take it. */
export type Issue = { path: (string | number)[]; message: string; fix?: { start: number; end: number; text: string } };
