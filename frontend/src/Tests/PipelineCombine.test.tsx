import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { PipelineFormula } from "@/features/pipelines/PipelineFormula";
import { PipelineLearningSummary } from "@/features/pipelines/PipelineLearningSummary";
import { PipelineScope } from "@/features/pipelines/PipelineScope";
import { combinedName, formulaName } from "@/features/pipelines/scope";
import { STEP_FAMILIES, stepDescription, stepFamily, stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { PipelineState } from "@/features/pipelines/diagnostics";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const text = (name: string, label: string, required = false): Field => ({
  name, label, type: "string", required, has_default: !required, nullable: !required,
  description: `${label} help`,
});
const result: Field = { name: "result", label: "Result", type: "enum", default: "add", has_default: true, options: ["replace", "add"] };
const component = (id: string, fields: Field[]): PipelineComponent => ({
  id, kind: "transform", label: id, description: "", input_type: "features", output_type: "features",
  strategies: ["static_baseline", "adaptive_stream"], fields,
});
const aggregate = component("prepare.aggregate", [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  result,
  { name: "function", label: "Function", type: "enum", default: "mean", has_default: true,
    options: ["mean", "sum", "min", "max", "std", "range"] },
  text("name", "Name"),
]);
const formula = component("prepare.formula", [text("expression", "Formula", true), text("name", "Name"), result]);
const gate = component("prepare.gate", [text("condition", "Condition", true)]);

const node = (step: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: step.id, params });
const definition = normalizeDefinition({
  strategy: "adaptive_stream", input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [],
});
const summary = (step: PipelineComponent, params?: PipelineNode["params"]) =>
  nodeSummary(node(step, params), step, definition);

describe("Combine and Gate steps in the composer", () => {
  it("sit in the add-step menu: Aggregate and Formula under Combine, Gate with the routes", () => {
    expect(STEP_FAMILIES[1]).toEqual({ id: "combine", label: "Combine" });
    expect(stepFamily("transform", "prepare.aggregate")).toBe("combine");
    expect(stepFamily("transform", "prepare.formula")).toBe("combine");
    expect(stepFamily("transform", "prepare.gate")).toBe("route");
    for (const step of [aggregate, formula, gate]) expect(stepDescription(step)).not.toBe("");
  });

  it("leave the settings with controls of their own out of the generic list", () => {
    const names = (step: PipelineComponent) => stepFields(node(step), step).map((field) => field.name);
    expect(names(aggregate)).toEqual(["function"]);
    expect(names(formula)).toEqual([]);
    expect(names(gate)).toEqual([]);
  });

  it("name the computed feature as core does", () => {
    expect(combinedName(node(formula), formula)).toBe("formula");
    expect(combinedName(node(aggregate), aggregate)).toBe("mean");
    expect(combinedName(node(aggregate, { function: "std" }), aggregate)).toBe("std");
    expect(combinedName(node(formula, { name: "power" }), formula)).toBe("power");
    expect(combinedName(node(gate), gate)).toBeUndefined();
    expect(formulaName("dc_voltage")).toBe("dc_voltage");
    expect(formulaName("dc-voltage")).toBe("`dc-voltage`");
  });

  it("say on the card what they compute or let through", () => {
    expect(summary(aggregate)).toEqual({ text: "Mean of every feature", chips: ["+ mean"] });
    expect(summary(aggregate, { apply_to: ["a", "b"], function: "max", name: "peak", result: "replace" }))
      .toEqual({ text: "Maximum of 2 features · Replaces them with peak" });
    expect(summary(formula, { expression: "dc_voltage *\n  dc_current", name: "power" }))
      .toEqual({ text: "power = dc_voltage * dc_current" });
    expect(summary(formula, { expression: "a - b", result: "replace" }))
      .toEqual({ text: "formula = a - b · Replaces its inputs" });
    expect(summary(formula)).toEqual({ text: "No formula yet" });
    expect(summary(gate, { condition: "dc_current > 1" })).toEqual({ text: "Only when dc_current > 1" });
    expect(summary(gate)).toEqual({ text: "No condition yet" });
  });
});

function formulaPanel(step: PipelineComponent, params: PipelineNode["params"], issues: { path: string[]; message: string }[] = []) {
  const changes: Record<string, JsonValue>[] = [];
  render(<PipelineFormula node={node(step, params)} component={step} features={["dc_voltage", "dc-current"]}
    featureLabels={{}} issues={issues} onChange={(next) => { changes.push(next); }} />);
  return changes;
}

describe("the formula editor", () => {
  it("inserts the features that arrive, in backticks where they need them", () => {
    const changes = formulaPanel(formula, { expression: "2 * " });
    const area = screen.getByRole("textbox", { name: "Formula" }) as HTMLTextAreaElement;
    area.setSelectionRange(4, 4);
    fireEvent.click(screen.getByRole("button", { name: "Insert dc-current" }));
    expect(changes).toEqual([{ expression: "2 * `dc-current`" }]);
  });

  it("shows the problem beside the formula and the step's result and name", () => {
    const changes = formulaPanel(formula, { expression: "a *" },
      [{ path: ["expression"], message: "The expression ends too early at character 4." }]);
    expect(screen.getByRole("alert").textContent).toBe("The expression ends too early at character 4.");
    expect(screen.getByRole("textbox", { name: "Formula" }).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Keeps the features and adds formula.")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).placeholder).toBe("formula");
    fireEvent.click(screen.getByRole("button", { name: "Replace features" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "power" } });
    expect(changes).toEqual([
      { expression: "a *", result: "replace" },
      { expression: "a *", name: "power" },
    ]);
  });

  it("writes a Gate's condition without a result or a name", () => {
    const changes = formulaPanel(gate, {});
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Keep features" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Condition" }), { target: { value: "dc_voltage > 1" } });
    expect(changes).toEqual([{ condition: "dc_voltage > 1" }]);
    expect(screen.getByText("Condition help")).toBeTruthy();
  });
});

describe("the scope of an Aggregate", () => {
  it("names its feature and keeps at least two features", () => {
    const changes: Record<string, JsonValue>[] = [];
    render(<PipelineScope node={node(aggregate, { apply_to: ["a", "b"], result: "replace" })} component={aggregate}
      features={["a", "b", "c"]} featureLabels={{ a: "A" }} issues={[]} onChange={(next) => { changes.push(next); }} />);
    // The sentence names features as the computed one is named.
    expect(screen.getByText("Replaces a and b with mean.")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).placeholder).toBe("mean");
    expect(screen.queryByRole("textbox", { name: "Suffix" })).toBeNull();
    expect((screen.getByRole("checkbox", { name: "A" }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "c" }));
    expect(changes).toEqual([{ result: "replace" }]);
  });
});

describe("the Prepare summary", () => {
  it("counts the observations a Gate held back", () => {
    const state = {
      preparation: { ready: true, observed: 3, required: 3, rejected: 0, held_back: 7 },
    } as unknown as PipelineState;
    render(<PipelineLearningSummary state={state} />);
    expect(screen.getByText("Held back by a Gate").nextSibling?.textContent).toBe("7");
  });
});
