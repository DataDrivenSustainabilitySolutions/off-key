import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { inCondition, suggestions, typedWord } from "@/features/pipelines/formula";
import { addComponent } from "@/features/pipelines/model";
import { PipelineFormula } from "@/features/pipelines/PipelineFormula";
import { PipelineLearningSummary } from "@/features/pipelines/PipelineLearningSummary";
import { PipelineScope } from "@/features/pipelines/PipelineScope";
import { combinedName, formulaName } from "@/features/pipelines/scope";
import { STEP_FAMILIES, stepFamily, stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { PipelineState } from "@/features/pipelines/diagnostics";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const text = (name: string, label: string, required = false): Field => ({
  name, label, type: "string", required, has_default: !required, nullable: !required,
  description: `${label} help`,
});
const result: Field = { name: "result", label: "Result", type: "enum", default: "add", has_default: true, options: ["replace", "add"] };
const component = (id: string, fields: Field[], group: PipelineComponent["group"] = "combine"): PipelineComponent => ({
  id, kind: "transform", group, label: id, description: "", input_type: "features", output_type: "features",
  fields,
});
const aggregate = component("prepare.aggregate", [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  result,
  { name: "function", label: "Function", type: "enum", default: "mean", has_default: true,
    options: ["mean", "sum", "min", "max", "std", "range"] },
  text("name", "Name"),
]);
const formula = component("prepare.formula", [text("expression", "Formula", true), text("name", "Name"), result]);
const gate = component("prepare.gate", [text("condition", "Condition", true)], "route");
const mute = component("prepare.mute", [text("condition", "Condition", true)], "route");
const condition = component("prepare.condition", [text("condition", "Condition", true), text("name", "Name")]);
const assignment = component("prepare.set", [text("expression", "Formula", true), text("name", "Name")]);
const constant = component("prepare.constant", [text("name", "Name"),
  { name: "value", label: "Value", type: "number", default: 0, has_default: true }]);

const node = (step: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: step.id, params });
const definition = normalizeDefinition({
  input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [],
});
const summary = (step: PipelineComponent, params?: PipelineNode["params"]) =>
  nodeSummary(node(step, params), step, definition);

describe("Combine and Gate steps in the composer", () => {
  it("sit in the add-step menu where the catalog files them, Combine second", () => {
    expect(STEP_FAMILIES[1]).toEqual({ id: "combine", label: "Combine" });
    expect(stepFamily(node(aggregate), aggregate)).toBe("combine");
    expect(stepFamily(node(gate), gate)).toBe("route");
    expect(stepFamily(node(mute), mute)).toBe("route");
    // A step the catalog does not list is still a transform.
    expect(stepFamily(node(formula), undefined)).toBe("transform");
  });

  it("leave the settings with controls of their own out of the generic list", () => {
    const names = (step: PipelineComponent) => stepFields(node(step), step).map((field) => field.name);
    expect(names(aggregate)).toEqual(["function"]);
    expect(names(formula)).toEqual([]);
    expect(names(gate)).toEqual([]);
    expect(names(mute)).toEqual([]);
  });

  it("name the computed feature as core does", () => {
    expect(combinedName(node(formula), formula)).toBe("formula");
    expect(combinedName(node(aggregate), aggregate)).toBe("mean");
    expect(combinedName(node(aggregate, { function: "std" }), aggregate)).toBe("std");
    expect(combinedName(node(formula, { name: "power" }), formula)).toBe("power");
    expect(combinedName(node(gate), gate)).toBeUndefined();
    expect(combinedName(node(mute), mute)).toBeUndefined();
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
    expect(summary(mute, { condition: "speed < 100" })).toEqual({ text: "No alarm while speed < 100" });
    expect(summary(mute)).toEqual({ text: "No condition yet" });
  });
});

type Issue = { path: string[]; message: string; fix?: { start: number; end: number; text: string } };
function formulaPanel(step: PipelineComponent, params: PipelineNode["params"], issues: Issue[] = [], range?: string) {
  const changes: Record<string, JsonValue>[] = [];
  render(<PipelineFormula node={node(step, params)} component={step} features={["dc_voltage", "dc-current"]}
    featureLabels={{ dc_voltage: "DC voltage" }} issues={issues} range={range} onChange={(next) => { changes.push(next); }} />);
  return changes;
}

/** Put the caret at the end of the formula, as typing there leaves it. */
function caretAtEnd(name = "Formula") {
  const area = screen.getByRole("textbox", { name }) as HTMLTextAreaElement;
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
  fireEvent.select(area);
  return area;
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

  it("writes the condition of a Mute alarms step under what it does", () => {
    const changes = formulaPanel(mute, {});
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Keep features" })).toBeNull();
    const area = screen.getByRole("textbox", { name: "Mute while" }) as HTMLTextAreaElement;
    expect(area.placeholder).toBe("speed < 100");
    fireEvent.change(area, { target: { value: "dc_voltage < 100" } });
    expect(changes).toEqual([{ condition: "dc_voltage < 100" }]);
  });
});

describe("a formula for each feature", () => {
  const phases = (params: PipelineNode["params"], features = ["L1", "L2", "L3", "mean"]) => {
    const changes: Record<string, JsonValue>[] = [];
    render(<PipelineFormula node={node(formula, params)} component={formula} features={features}
      featureLabels={{ L1: "L1", L2: "L2", L3: "L3" }} issues={[]} onChange={(next) => { changes.push(next); }} />);
    return changes;
  };

  it("starts with the readings that arrive and leaves the name to the suffix", () => {
    const changes = phases({ expression: "L1 / mean - 1", name: "d1" });
    expect(screen.getByRole("button", { name: "One feature" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "For each feature" }));
    expect(changes).toEqual([{ expression: "L1 / mean - 1", apply_to: ["L1", "L2", "L3"] }]);
  });

  it("starts with the features that follow one reading, when the check knows them", () => {
    const changes: Record<string, JsonValue>[] = [];
    render(<PipelineFormula node={node(formula, { expression: "x" })} component={formula}
      features={["phase_a", "phase_b", "mean"]} readings={["phase_a", "phase_b"]} featureLabels={{}} issues={[]}
      onChange={(next) => { changes.push(next); }} />);
    fireEvent.click(screen.getByRole("button", { name: "For each feature" }));
    expect(changes).toEqual([{ expression: "x", apply_to: ["phase_a", "phase_b"] }]);
  });

  it("offers x, names what it adds and goes back to one feature", () => {
    const changes = phases({ expression: "x / mean - 1", apply_to: ["L1", "L2", "L3"], suffix: "dev" });
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.getByText("x stands for L1, L2 and L3, one after another.")).toBeTruthy();
    expect(screen.getByText("Keeps the features and adds L1_dev, L2_dev and L3_dev.")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Suffix" }) as HTMLInputElement).value).toBe("dev");
    fireEvent.click(screen.getByRole("button", { name: "Insert x, each chosen feature" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "L2" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace values" }));
    fireEvent.click(screen.getByRole("button", { name: "One feature" }));
    expect(changes.slice(1)).toEqual([
      { expression: "x / mean - 1", apply_to: ["L1", "L3"], suffix: "dev" },
      { expression: "x / mean - 1", apply_to: ["L1", "L2", "L3"], suffix: "dev", result: "replace" },
      { expression: "x / mean - 1" },
    ]);
    expect(changes[0]!.expression).toMatch(/x/);
  });

  it("says on the card which features it runs on", () => {
    expect(summary(formula, { expression: "x / mean - 1", apply_to: ["L1", "L2"], suffix: "dev" }).text)
      .toBe("x / mean - 1 for L1 and L2 · Adds *_dev");
    expect(summary(formula, { expression: "x * 2", apply_to: ["L1"], result: "replace" }).text)
      .toBe("x * 2 for L1 · Replaces them");
    expect(combinedName(node(formula, { expression: "x", apply_to: ["L1"] }), formula)).toBeUndefined();
  });
});

describe("completing a formula", () => {
  it("finds the word before the caret, also inside backticks, but not in a number", () => {
    expect(typedWord("2 * dc_vo", 9)).toEqual({ start: 4, end: 9, prefix: "dc_vo", quoted: false });
    expect(typedWord("2 * dc_vo + 1", 7)).toEqual({ start: 4, end: 9, prefix: "dc_", quoted: false });
    expect(typedWord("`dc-c` + 1", 3)).toEqual({ start: 0, end: 6, prefix: "dc", quoted: true });
    expect(typedWord("1e5", 3)).toBeUndefined();
    expect(typedWord("a + ", 4)).toBeUndefined();
  });

  it("offers features first, then functions, and and/or/not only in a condition", () => {
    const labels = { dc_voltage: "DC voltage" };
    const names = (prefix: string, condition = false, quoted = false) =>
      suggestions({ prefix, quoted }, ["dc_voltage", "dc-current", "max"], labels, condition).map((item) => item.value);
    expect(names("dc")).toEqual(["dc_voltage", "dc-current"]);
    expect(names("ma")).toEqual(["max", "max"]);
    // A feature is found by any part of its name, a function or keyword by its beginning.
    expect(names("o", true)).toEqual(["or", "dc_voltage"]);
    expect(names("o")).toEqual(["dc_voltage"]);
    expect(names("lo")).toEqual(["log", "log1p"]);
    expect(names("c", false, true)).toEqual(["dc_voltage", "dc-current"]);
    // A finished word needs no list.
    expect(names("dc_voltage")).toEqual([]);
  });

  it("completes with the keyboard and writes backticks where a name needs them", () => {
    const changes = formulaPanel(formula, { expression: "2 * dc" });
    const area = caretAtEnd();
    const list = screen.getByRole("listbox", { name: "Suggestions" });
    expect([...list.querySelectorAll("[role=option]")].map((option) => option.textContent))
      .toEqual(["dc_voltageDC voltage", "`dc-current`"]);
    expect(area.getAttribute("aria-activedescendant")).toBe(list.querySelector("[aria-selected=true]")!.id);
    fireEvent.keyDown(area, { key: "ArrowDown" });
    fireEvent.keyDown(area, { key: "Enter" });
    expect(changes).toEqual([{ expression: "2 * `dc-current`" }]);
  });

  it("opens a function's parentheses", () => {
    const changes = formulaPanel(formula, { expression: "sq" });
    caretAtEnd();
    fireEvent.click(screen.getByRole("option", { name: /sqrt/ }));
    expect(changes).toEqual([{ expression: "sqrt()" }]);
  });

  it("writes a constant with its parentheses", () => {
    const changes = formulaPanel(formula, { expression: "2 * p" });
    caretAtEnd();
    fireEvent.click(screen.getByRole("option", { name: /pi\(\)/ }));
    expect(changes).toEqual([{ expression: "2 * pi()" }]);
  });

  it("offers the rounding, wrapping and combining functions by what is typed", () => {
    const names = (prefix: string) =>
      suggestions({ prefix, quoted: false }, [], {}, false).map((item) => item.value);
    expect(names("ro")).toEqual(["round"]);
    expect(names("mo")).toEqual(["mod"]);
    expect(names("me")).toEqual(["mean"]);
    expect(names("hy")).toEqual(["hypot"]);
    expect(names("si")).toEqual(["sign", "sin"]);
    expect(names("at")).toEqual(["atan2"]);
  });

  it("closes the list with Escape and keeps the panel open", () => {
    const outside: string[] = [];
    const { container } = render(<div onKeyDown={(event) => { outside.push(event.key); }}>
      <PipelineFormula node={node(gate, { condition: "dc_voltage > 1 an" })} component={gate} features={["dc_voltage"]}
        featureLabels={{}} issues={[]} onChange={() => {}} />
    </div>);
    const area = caretAtEnd("Condition");
    expect(screen.getByRole("option", { name: /and/ })).toBeTruthy();
    fireEvent.keyDown(area, { key: "Escape" });
    expect(container.querySelector("[role=listbox]")).toBeNull();
    expect(outside).toEqual([]);
  });

  it("fixes a misspelt name with one click and shows the computed range", () => {
    const changes = formulaPanel(formula, { expression: "dc_votage * 2" }, [{
      path: ["expression"], message: "Unknown feature dc_votage at character 1. Did you mean dc_voltage?",
      fix: { start: 0, end: 9, text: "dc_voltage" },
    }], "0 to 1,200");
    fireEvent.click(screen.getByRole("button", { name: "Use dc_voltage" }));
    expect(changes).toEqual([{ expression: "dc_voltage * 2" }]);
    expect(screen.getByText("Range").parentElement?.textContent).toBe("Range 0 to 1,200");
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
    expect(screen.queryByText("Scored with alarms muted")).toBeNull();
  });

  it("counts the observations scored while a Mute alarms step held alarms back", () => {
    const state = {
      preparation: { ready: true, observed: 3, required: 3, rejected: 0, held_back: 0, muted: 12 },
    } as unknown as PipelineState;
    render(<PipelineLearningSummary state={state} />);
    expect(screen.getByText("Scored with alarms muted").nextSibling?.textContent).toBe("12");
    expect(screen.queryByText("Held back by a Gate")).toBeNull();
  });
});

describe("numeric primitives", () => {
  it("edits a reusable condition without offering filtering or replacement controls", () => {
    const changes = formulaPanel(condition, { name: "running", condition: "dc_voltage > 10" });
    expect(screen.getByText("Keeps every observation and adds running: 1 when the condition holds, 0 otherwise.")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Computes" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Result" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Condition" }), { target: { value: "dc_voltage > 20" } });
    expect(changes[changes.length - 1]).toEqual({ name: "running", condition: "dc_voltage > 20" });
    expect(stepFields(node(condition), condition)).toEqual([]);
  });

  it("assigns an existing feature without removing the formula's other inputs", () => {
    const changes = formulaPanel(assignment, { name: "dc-current", expression: "if(dc_voltage > 0, 1, 0)" });
    expect(screen.getByText(/Other features stay unchanged/)).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Result" })).toBeNull();
    expect(screen.queryByRole("button", { name: "For each feature" })).toBeNull();
    // The name offers the arriving features, which makes it a combobox.
    fireEvent.change(screen.getByRole("combobox", { name: "Name" }), { target: { value: "dc_voltage" } });
    expect(changes[changes.length - 1]?.name).toBe("dc_voltage");
    expect(stepFields(node(assignment), assignment)).toEqual([]);
  });

  it("suggests conditional expressions and Boolean operators inside their conditions", () => {
    expect(suggestions({ prefix: "if", quoted: false }, [], {}, false)[0]?.value).toBeUndefined();
    expect(suggestions({ prefix: "i", quoted: false }, [], {}, false).some(item => item.value === "if")).toBe(true);
    formulaPanel(formula, { expression: "if(dc_voltage > 0 an" });
    caretAtEnd();
    expect(screen.getByRole("option", { name: /and/ })).toBeTruthy();
  });

  it("keeps and, or and not out of the values an if chooses between", () => {
    const { container } = render(<PipelineFormula node={node(formula, { expression: "if(dc_voltage > 0, dc_voltage an" })}
      component={formula} features={["dc_voltage"]} featureLabels={{}} issues={[]} onChange={() => {}} />);
    caretAtEnd();
    expect(container.querySelector("[role=listbox]")).toBeNull();
  });

  it("knows where a condition is being written", () => {
    const at = (text: string, condition = false) => inCondition(text, text.length, condition);
    // A formula takes numbers; the first argument of if is a condition.
    expect(at("a + ")).toBe(false);
    expect(at("if(a > 1 ")).toBe(true);
    expect(at("2 * if (a > 1 and (b < 2 ")).toBe(true);
    expect(at("if(not (a > 1 ")).toBe(true);
    expect(at("if(a > 1, b ")).toBe(false);
    expect(at("if(a > 1, b, c) + ")).toBe(false);
    expect(at("if(a > max(b, ")).toBe(false);
    expect(at("if(a > 1, if(b < 2 ")).toBe(true);
    // A comma or a parenthesis in a quoted name is part of the name.
    expect(at("if(`a,b(` > 1 ")).toBe(true);
    // A Gate or Condition is a condition throughout, except among a function's numbers.
    expect(at("a > 1 ", true)).toBe(true);
    expect(at("(a > 1 or b < 2) ", true)).toBe(true);
    expect(at("max(a, ", true)).toBe(false);
    expect(at("if(a > 1, b ", true)).toBe(false);
  });

  it("offers the arriving features as names a Set feature can replace", () => {
    formulaPanel(assignment, { expression: "dc_voltage * 2" });
    const name = screen.getByRole("combobox", { name: "Name" }) as HTMLInputElement;
    expect([...name.list!.options].map((item) => item.value)).toEqual(["dc_voltage", "dc-current"]);
    // A Formula always adds a new name, so it offers none.
    formulaPanel(formula, { expression: "dc_voltage * 2" });
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).list).toBeNull();
  });

  it("gives added constants distinct names and describes their values and flags", () => {
    let document = { definition, layout: { nodes: {} } };
    document = addComponent(document, constant);
    document = addComponent(document, constant);
    expect(document.definition.nodes.map(item => combinedName(item, constant))).toEqual(["constant", "constant_2"]);
    expect(summary(constant, { name: "limit", value: 42 }).text).toBe("limit = 42");
    expect(summary(condition, { name: "high", condition: "dc_voltage > 42" }).text)
      .toBe("high: 1 when dc_voltage > 42, otherwise 0");
  });

  it("offers a quantile setting only for the quantile statistic", () => {
    const rolling = component("prepare.rolling", [
      { name: "statistic", label: "Statistic", type: "enum", default: "mean", has_default: true },
      { name: "quantile", label: "Quantile", type: "number", default: .5, has_default: true,
        shown_when: { field: "statistic", equals: ["quantile"] } },
    ], "prepare");
    expect(stepFields(node(rolling), rolling).map(field => field.name)).toEqual(["statistic"]);
    expect(stepFields(node(rolling, { statistic: "quantile" }), rolling).map(field => field.name))
      .toEqual(["statistic", "quantile"]);
    expect(summary(rolling, { statistic: "quantile", quantile: .9, window_size: 5 }).text)
      .toBe("Quantile 0.9 of last 5");
    // A score or a rank places the latest value within the window.
    const rolled = (statistic: string) => summary(rolling, { statistic, window_size: 60 }).text;
    expect(["zscore", "robust_zscore", "rank"].map(rolled))
      .toEqual(["Z-score within last 60", "Robust z-score within last 60", "Rank within last 60"]);
    expect(["rms", "skewness", "kurtosis"].map(rolled))
      .toEqual(["Root mean square of last 60", "Skewness of last 60", "Excess kurtosis of last 60"]);
  });
});
