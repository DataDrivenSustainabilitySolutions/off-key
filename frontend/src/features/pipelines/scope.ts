import type { JsonValue } from "@/types/monitoring";
import type { PipelineIssue } from "@/types/pipelines.generated";
import type { PipelineComponent, PipelineNode } from "./contracts";

/** The settings that say which features a step uses and where its output goes. */
export const SCOPE_FIELDS = new Set(["apply_to", "result", "suffix"]);

export type StepScope = {
  /** The features the step uses; undefined uses every feature that arrives. */
  applyTo?: string[];
  add: boolean;
  /** Steps that map each feature to one value name their added features with it. */
  suffix?: string;
  elementwise: boolean;
};

const strings = (value: JsonValue | undefined) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;

export const hasScope = (component?: PipelineComponent) =>
  !!component?.fields.some((field) => field.name === "apply_to");

/** A step's scope as the compiler reads it, with the catalog's default suffix. */
export function stepScope(node: PipelineNode, component?: PipelineComponent): StepScope | undefined {
  if (!component || !hasScope(component)) return undefined;
  const suffixField = component.fields.find((field) => field.name === "suffix");
  const suffix = typeof node.params.suffix === "string" && node.params.suffix
    ? node.params.suffix
    : typeof suffixField?.default === "string" ? suffixField.default : undefined;
  return { applyTo: strings(node.params.apply_to), add: node.params.result === "add", suffix, elementwise: !!suffixField };
}

export const addedName = (feature: string, suffix: string) => `${feature}_${suffix}`;

/** Errors block applying a design; warnings are shown and do not. */
export const isWarning = (issue: Pick<PipelineIssue, "severity">) => issue.severity === "warning";
