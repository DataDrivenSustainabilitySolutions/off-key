import type { JsonValue } from "@/types/monitoring";
import type { FieldDescriptor } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineDefinition, PipelineNode } from "./contracts";
import { detectorIds } from "./model";
import { addedName, combinedName, eachSuffix, formulaEach, listed, SCOPE_FIELDS, setting, stepScope } from "./scope";
import { fusionChoice } from "./steps";

/** What a card says about its settings: one line of text, or the features it keeps. */
export type NodeSummary = { text?: string; chips?: string[] };

const count = (value: number, noun: string) => `${value.toLocaleString()} ${noun}${value === 1 ? "" : "s"}`;
const number = (value: number) =>
  Number.isInteger(value) ? value.toLocaleString() : Number(value.toPrecision(4)).toLocaleString();
const strings = (value: JsonValue | undefined) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const sentence = (label: string) => label.charAt(0) + label.slice(1).toLowerCase();

const isRecord = (value: JsonValue | undefined): value is Record<string, JsonValue> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Whether a setting holds its default, comparing lists and nested settings by value. */
function same(left: JsonValue | undefined, right: JsonValue | undefined): boolean {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => same(item, right[index]));
  if (isRecord(left) && isRecord(right))
    return [...new Set([...Object.keys(left), ...Object.keys(right)])].every((key) => same(left[key], right[key]));
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
  // The policy names how it combines detectors on its own, and only when there are several.
  const changed = component.fields.filter((field) => !SCOPE_FIELDS.has(field.name) && field.name !== "fusion"
    && node.params[field.name] !== undefined && !same(node.params[field.name], field.default));
  const lines = changed.map((field) => formatted(field, node.params[field.name]!));
  const shown = lines.filter((line): line is string => !!line).slice(0, 2);
  const rest = changed.length - shown.length;
  return [...shown, ...(rest ? [`${count(rest, "more setting")}`] : [])].join(" · ") || undefined;
}

/** The features a scoped step uses as chips, or the features it adds as "+ name". */
function scopeSummary(
  node: PipelineNode,
  component: PipelineComponent | undefined,
  labels: Map<string, string>,
): NodeSummary | undefined {
  const scope = stepScope(node, component);
  if (!scope) return undefined;
  const used = scope.applyTo;
  const computed = combinedName(node, component);
  if (computed !== undefined)
    return scope.add ? { chips: [`+ ${computed}`] } : { text: `Replaces them with ${computed}` };
  if (scope.add && scope.elementwise)
    return used ? { chips: used.map((name) => `+ ${addedName(name, scope.suffix ?? "new")}`) }
      : { text: `Adds *_${scope.suffix ?? "new"}` };
  return { text: scope.add ? "Keeps its inputs" : undefined, chips: used?.map((name) => labels.get(name) ?? name) };
}

const STATISTICS: Record<string, string> = {
  mean: "Mean", median: "Median", min: "Minimum", max: "Maximum", std: "Standard deviation", range: "Range",
};
const AGGREGATES: Record<string, string> = { ...STATISTICS, sum: "Sum" };
const FUNCTIONS: Record<string, string> = {
  log: "log(x)", log1p: "log(1 + x)", sqrt: "√x", abs: "|x|", square: "x²",
};

function linear(scale: number, offset: number) {
  const term = scale === 1 ? "x" : `${number(scale)} × x`;
  if (offset === 0) return scale === 1 ? "x, unchanged" : term;
  return `${term} ${offset < 0 ? "−" : "+"} ${number(Math.abs(offset))}`;
}

/** A formula or condition on one line. */
const written = (value: JsonValue | undefined) => typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";

/** What a Prepare step does, in the words of its settings. */
function prepareSummary(node: PipelineNode, component: PipelineComponent | undefined): string | undefined {
  const value = (name: string) => setting(node, component, name);
  const amount = (name: string, fallback: number) => {
    const raw = value(name);
    return typeof raw === "number" ? raw : fallback;
  };
  switch (node.component) {
    case "prepare.smooth": {
      const window = number(amount("window_size", 10));
      return value("method") === "rolling" ? `Mean of last ${window}` : `Exponential over ${window}`;
    }
    case "prepare.despike":
      return `Window ${number(amount("window_size", 11))} · limit ${number(amount("threshold", 3))} MAD`;
    case "prepare.change": {
      const lag = amount("lag", 1);
      if (value("mode") === "lag") return `Value ${count(lag, "observation")} back`;
      return `${value("mode") === "percent" ? "Percent change" : "Difference"} over ${count(lag, "observation")}`;
    }
    case "prepare.rolling":
      return `${STATISTICS[String(value("statistic"))] ?? "Mean"} of last ${number(amount("window_size", 60))}`;
    case "prepare.math":
      return value("function") === "linear"
        ? linear(amount("scale", 1), amount("offset", 0))
        : FUNCTIONS[String(value("function"))];
    case "prepare.range": {
      const low = value("low");
      const high = value("high");
      const verb = value("action") === "skip" ? "Skip" : "Clip";
      if (typeof low === "number" && typeof high === "number")
        return `${verb} ${verb === "Skip" ? "outside" : "to"} ${number(low)} to ${number(high)}`;
      if (typeof low === "number") return `${verb} below ${number(low)}`;
      if (typeof high === "number") return `${verb} above ${number(high)}`;
      return;
    }
    case "prepare.aggregate": {
      const used = strings(value("apply_to"));
      return `${AGGREGATES[String(value("function"))] ?? "Mean"} of ${used.length ? count(used.length, "feature") : "every feature"}`;
    }
    case "prepare.formula": {
      const formula = written(value("expression"));
      if (!formula) return "No formula yet";
      const each = formulaEach(node);
      if (each) {
        const added = value("result") !== "replace";
        return `${formula} for ${each.length ? listed(each) : "no feature yet"}${added ? ` · Adds *_${eachSuffix(node)}` : " · Replaces them"}`;
      }
      return `${combinedName(node, component)} = ${formula}${value("result") === "replace" ? " · Replaces its inputs" : ""}`;
    }
    case "prepare.gate": {
      const condition = written(value("condition"));
      return condition ? `Only when ${condition}` : "No condition yet";
    }
  }
}

/** A card's one-line account of what it does with its inputs. Presentation only. */
export function nodeSummary(
  node: PipelineNode,
  component: PipelineComponent | undefined,
  definition: PipelineDefinition,
): NodeSummary {
  const labels = new Map(definition.input_slots.map((slot) => [slot.id, slot.label || slot.id]));
  const base = settingsSummary(node, component, definition, labels);
  const detectors = detectorIds(definition).length;
  if (node.kind === "policy" && detectors > 1)
    return { text: [`${fusionChoice(node).label} of ${detectors} detectors`, base.text].filter(Boolean).join(" · ") };
  const scope = scopeSummary(node, component, labels);
  if (!scope) return base;
  return {
    text: [base.text, scope.text].filter(Boolean).join(" · ") || undefined,
    chips: scope.chips ?? base.chips,
  };
}

function settingsSummary(
  node: PipelineNode,
  component: PipelineComponent | undefined,
  definition: PipelineDefinition,
  labels: Map<string, string>,
): NodeSummary {
  const params = node.params;
  const prepared = prepareSummary(node, component);
  if (prepared) return { text: prepared };
  switch (node.component) {
    case "source.aligned":
      return { text: count(definition.input_slots.length, "input slot") };
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
    case "static.robust_scaler":
      return {};
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
