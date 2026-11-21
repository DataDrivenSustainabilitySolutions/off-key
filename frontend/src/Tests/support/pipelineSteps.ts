import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineDefinition,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { nodeSummary } from "@/features/pipelines/summaries";

/** Hand-built catalog entries for the step tests, in the catalog's own shape. */
export type Field = PipelineComponent["fields"][number];

export const option = (name: string, value: string, options: string[]): Field =>
  ({ name, label: name, type: "enum", default: value, has_default: true, options });

export const text = (name: string, label: string, required = false): Field => ({
  name, label, type: "string", required, has_default: !required, nullable: !required,
  ...(required ? {} : { default: null }), description: `${label} help`,
});

/** The three settings every Prepare step starts with: which features, replace or add, and the suffix. */
export const scopeFields = (result = "replace"): Field[] => [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  option("result", result, ["replace", "add"]),
  { name: "suffix", label: "Suffix", type: "string", default: null, has_default: true, nullable: true },
];

export const step = (id: string, fields: Field[], group: PipelineComponent["group"] = "prepare"): PipelineComponent => ({
  id, kind: "transform", group, label: id, description: "", input_type: "features", output_type: "features", fields,
});

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
