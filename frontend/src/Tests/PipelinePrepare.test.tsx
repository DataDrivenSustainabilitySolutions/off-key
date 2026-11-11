import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { rejectionSummary } from "@/features/pipelines/diagnostics";
import { PipelineScope } from "@/features/pipelines/PipelineScope";
import { defaultSuffix, stepScope } from "@/features/pipelines/scope";
import { STEP_FAMILIES, stepDescription, stepFamily, stepFields } from "@/features/pipelines/steps";
import { changeDetector } from "@/features/pipelines/learning";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const option = (name: string, value: string, options: string[]): Field =>
  ({ name, label: name, type: "enum", default: value, has_default: true, options });
const amount = (name: string, value: number, type: "integer" | "number" = "number", nullable = false): Field =>
  ({ name, label: name, type, default: value, has_default: true, nullable });

/** The catalog's Prepare steps, as core describes them. */
function prepare(id: string, fields: Field[], result = "replace"): PipelineComponent {
  return {
    id, kind: "transform", label: id, description: "", input_type: "features", output_type: "features",
    fields: [
      { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
      option("result", result, ["replace", "add"]),
      { name: "suffix", label: "Suffix", type: "string", default: null, has_default: true, nullable: true },
      ...fields,
    ],
  };
}
const smooth = prepare("prepare.smooth", [
  option("method", "exponential", ["exponential", "rolling"]), amount("window_size", 10, "integer"),
]);
const despike = prepare("prepare.despike", [amount("window_size", 11, "integer"), amount("threshold", 3)]);
const change = prepare("prepare.change", [
  option("mode", "difference", ["difference", "percent", "lag"]), amount("lag", 1, "integer"),
], "add");
const rolling = prepare("prepare.rolling", [
  option("statistic", "mean", ["mean", "median", "min", "max", "std", "range"]), amount("window_size", 60, "integer"),
], "add");
const math = prepare("prepare.math", [
  option("function", "log", ["log", "log1p", "sqrt", "abs", "square", "linear"]), amount("scale", 1), amount("offset", 0),
]);
const range = prepare("prepare.range", [
  amount("low", 0, "number", true), amount("high", 1, "number", true), option("action", "clip", ["clip", "skip"]),
]);
const STEPS = [smooth, despike, change, rolling, math, range];

const node = (component: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: component.id, params });
const definition = normalizeDefinition({
  input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [],
});
const summary = (component: PipelineComponent, params?: PipelineNode["params"]) =>
  nodeSummary(node(component, params), component, definition);

describe("Prepare steps in the composer", () => {
  it("lead the add-step menu, each with one line of what it does", () => {
    expect(STEP_FAMILIES[0]).toEqual({ id: "prepare", label: "Prepare" });
    for (const component of STEPS) {
      expect(stepFamily("transform", component.id)).toBe("prepare");
      expect(stepDescription(component)).not.toBe("");
    }
  });

  it("name added features after their settings, as the compiler does", () => {
    const names = ([
      [smooth, {}], [smooth, { window_size: 30 }], [despike, {}], [change, {}],
      [change, { mode: "percent", lag: 12 }], [change, { mode: "lag", lag: 3 }], [rolling, {}],
      [rolling, { statistic: "std", window_size: 5 }], [math, {}], [math, { function: "linear" }], [range, {}],
    ] as [PipelineComponent, PipelineNode["params"]][]).map(([component, params]) => defaultSuffix(node(component, params), component));
    expect(names).toEqual([
      "smooth10", "smooth30", "despiked", "diff1", "pct12", "lag3", "mean60", "std5", "log", "scaled", "clipped",
    ]);
  });

  it("read Change and Rolling statistic as adding by default", () => {
    expect(stepScope(node(change), change)).toEqual({ applyTo: undefined, add: true, suffix: "diff1", elementwise: true });
    expect(stepScope(node(change, { result: "replace" }), change)?.add).toBe(false);
    expect(stepScope(node(smooth), smooth)?.add).toBe(false);
    expect(stepScope(node(rolling, { suffix: "avg" }), rolling)?.suffix).toBe("avg");
  });

  it("say on the card what the step does and which features it adds", () => {
    expect(summary(smooth)).toEqual({ text: "Exponential over 10" });
    expect(summary(smooth, { method: "rolling", window_size: 5 })).toEqual({ text: "Mean of last 5" });
    expect(summary(despike)).toEqual({ text: "Window 11 · limit 3 MAD" });
    expect(summary(change)).toEqual({ text: "Difference over 1 observation · Adds *_diff1" });
    expect(summary(change, { mode: "lag", lag: 3, apply_to: ["dc_voltage"] }))
      .toEqual({ text: "Value 3 observations back", chips: ["+ dc_voltage_lag3"] });
    expect(summary(rolling, { statistic: "std", window_size: 5, result: "replace" }))
      .toEqual({ text: "Standard deviation of last 5" });
    expect(summary(math)).toEqual({ text: "log(x)" });
    expect(summary(math, { function: "linear", scale: 2, offset: -3 })).toEqual({ text: "2 × x − 3" });
    expect(summary(math, { function: "linear" })).toEqual({ text: "x, unchanged" });
    expect(summary(range)).toEqual({ text: "Clip to 0 to 1" });
    expect(summary(range, { action: "skip", high: 50 })).toEqual({ text: "Skip outside 0 to 50" });
    expect(summary(range, { high: null })).toEqual({ text: "Clip below 0" });
  });

  it("list scale and offset only for a linear Math step", () => {
    const names = (params: PipelineNode["params"]) => stepFields(node(math, params), math).map((field) => field.name);
    expect(names({})).toEqual(["function"]);
    expect(names({ function: "linear" })).toEqual(["function", "scale", "offset"]);
    expect(stepFields(node(rolling), rolling).map((field) => field.name)).toEqual(["statistic", "window_size"]);
  });

  it("stay as they are when the detector after them learns differently", () => {
    const detector = (id: string, learning: PipelineComponent["learning"]): PipelineComponent => ({
      id, kind: "detector", label: id, description: "", learning, fields: [], input_type: "features", output_type: "scores",
    });
    const fitted = detector("detector:fitted", "batch");
    const definition = normalizeDefinition({
      input_slots: [{ id: "dc_voltage", label: "" }],
      nodes: [
        { id: "smooth", kind: "transform", component: "prepare.smooth", params: { window_size: 4 } },
        { id: "model", kind: "detector", component: "detector:continuous" },
      ],
      edges: [{ source: "smooth", target: "model" }],
    });
    const changed = changeDetector(definition, "model", fitted, [...STEPS, detector("detector:continuous", "online"), fitted]);
    expect(changed.converted).toEqual([]);
    expect(changed.definition.nodes[0]).toEqual(definition.nodes[0]);
    expect(changed.definition.nodes[1]?.component).toBe("detector:fitted");
  });
});

function scope(component: PipelineComponent, params: PipelineNode["params"]) {
  const changes: Record<string, JsonValue>[] = [];
  render(<PipelineScope node={node(component, params)} component={component} features={["dc_voltage", "temp"]}
    featureLabels={{}} issues={[]} onChange={(next) => { changes.push(next); }} />);
  return changes;
}
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

describe("the Result of a Prepare step", () => {
  it("starts from the step's own default and leaves it out when chosen again", () => {
    const changes = scope(change, {});
    expect(pressed("Add new features")).toBe("true");
    expect(screen.getByText("Keeps the values and adds dc_voltage_diff1 and temp_diff1.")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Suffix" }) as HTMLInputElement).placeholder).toBe("diff1");

    fireEvent.click(screen.getByRole("button", { name: "Replace values" }));
    expect(changes).toEqual([{ result: "replace" }]);
  });

  it("returns to adding by dropping the explicit choice", () => {
    const changes = scope(rolling, { result: "replace" });
    fireEvent.click(screen.getByRole("button", { name: "Add new features" }));
    expect(changes).toEqual([{}]);
  });

  it("cannot add features while a Range check skips observations", () => {
    scope(range, { action: "skip" });
    expect((screen.getByRole("button", { name: "Add new features" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Skips observations outside the range; the values that pass stay the same.")).toBeTruthy();
  });
});

describe("skipped observations", () => {
  it("are counted by reason", () => {
    expect(rejectionSummary({ out_of_range: 2, non_finite: 1 }))
      .toBe("Skipped 3 observations: 2 outside the range, 1 not a finite number.");
    expect(rejectionSummary({ out_of_domain: 1 })).toBe("Skipped 1 observation: 1 outside the function's domain.");
    // A learned step or the detector that failed without changing what it learned.
    expect(rejectionSummary({ error: 2 })).toBe("Skipped 2 observations: 2 with an error.");
    expect(rejectionSummary({})).toBeUndefined();
    expect(rejectionSummary(undefined)).toBeUndefined();
  });
});
