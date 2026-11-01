import type { JsonValue } from "@/types/monitoring";
import type { FieldDescriptor } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineDefinition, PipelineNode } from "./contracts";

/** What a card says about its settings: one line of text, or the features it keeps. */
export type NodeSummary = { text?: string; chips?: string[] };

const count = (value: number, noun: string) => `${value.toLocaleString()} ${noun}${value === 1 ? "" : "s"}`;
const number = (value: number) =>
  Number.isInteger(value) ? value.toLocaleString() : Number(value.toPrecision(4)).toLocaleString();
const strings = (value: JsonValue | undefined) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const sentence = (label: string) => label.charAt(0) + label.slice(1).toLowerCase();

function same(left: JsonValue | undefined, right: JsonValue | undefined): boolean {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => same(item, right[index]));
  return (left ?? null) === (right ?? null);
}

function formatted(field: FieldDescriptor, value: JsonValue): string | undefined {
  if (typeof value === "boolean") return `${sentence(field.label)} ${value ? "on" : "off"}`;
  if (typeof value === "number") return `${sentence(field.label)} ${number(value)}`;
  if (typeof value === "string") return `${sentence(field.label)} ${value.replace(/_/g, " ")}`;
  if (field.type === "number_pair" && Array.isArray(value) && value.length === 2
    && typeof value[0] === "number" && typeof value[1] === "number")
    return `${sentence(field.label)} ${number(value[0])} to ${number(value[1])}`;
}

/** Settings that differ from the catalogue defaults, at most two, then a count of the rest. */
function changedSettings(node: PipelineNode, component: PipelineComponent) {
  const changed = component.fields.filter((field) =>
    node.params[field.name] !== undefined && !same(node.params[field.name], field.default));
  const lines = changed.map((field) => formatted(field, node.params[field.name]!));
  const shown = lines.filter((line): line is string => !!line).slice(0, 2);
  const rest = changed.length - shown.length;
  return [...shown, ...(rest ? [`${count(rest, "more setting")}`] : [])].join(" · ") || undefined;
}

/** A card's one-line account of what it does with its inputs. Presentation only. */
export function nodeSummary(
  node: PipelineNode,
  component: PipelineComponent | undefined,
  definition: PipelineDefinition,
): NodeSummary {
  const labels = new Map(definition.input_slots.map((slot) => [slot.id, slot.label || slot.id]));
  const params = node.params;
  switch (node.component) {
    case "source.aligned":
      return { text: count(definition.input_slots.length, "reading") };
    case "features.select": {
      const features = strings(params.features);
      return features.length ? { chips: features.map((name) => labels.get(name) ?? name) } : { text: "No features chosen" };
    }
    case "features.rename": {
      const renamed = params.mapping && typeof params.mapping === "object" && !Array.isArray(params.mapping)
        ? Object.keys(params.mapping).length : 0;
      return { text: renamed ? `Renames ${count(renamed, "feature")}` : "No names changed" };
    }
    case "features.merge":
      return { text: `${count(definition.edges.filter((edge) => edge.target === node.id).length, "input")}, in order` };
    case "static.min_max_scaler":
    case "adaptive.min_max_scaler": {
      const range = Array.isArray(params.feature_range) ? params.feature_range : [0, 1];
      const [low, high] = range.map((value) => (typeof value === "number" ? number(value) : "?"));
      return { text: `Range ${low} to ${high}${params.clip === true ? " · clipped" : ""}` };
    }
    case "static.standard_scaler":
    case "adaptive.standard_scaler":
      return params.with_std === false ? { text: "Centering only" } : {};
    case "static.pca":
    case "static.random_projection":
    case "adaptive.uncentered_pca":
    case "adaptive.random_projection":
      return { text: count(typeof params.n_components === "number" ? params.n_components : 1, "component") };
    case "policy.quantile": {
      // The threshold freezes at this quantile of the calibration scores.
      const quantile = typeof params.quantile === "number" ? params.quantile : 1;
      return { text: quantile === 1 ? "Above the calibration maximum" : `Above calibration quantile ${number(quantile)}` };
    }
  }
  return component ? { text: changedSettings(node, component) } : {};
}
