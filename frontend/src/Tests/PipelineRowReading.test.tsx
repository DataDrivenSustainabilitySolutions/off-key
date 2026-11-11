import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { calculateLine, writtenNames } from "@/features/pipelines/formula";
import { PipelineFormula } from "@/features/pipelines/PipelineFormula";
import { PipelineAgainst } from "@/features/pipelines/PipelineScope";
import { defaultSuffix } from "@/features/pipelines/scope";
import { CONDITION_STEPS, FORMULA_STEPS, stepDescription, stepFamily, stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const option = (name: string, value: string, options: string[]): Field =>
  ({ name, label: name, type: "enum", default: value, has_default: true, options });
const text = (name: string, label: string, required = false): Field => ({
  name, label, type: "string", required, has_default: !required, nullable: !required,
  ...(required ? {} : { default: null }), description: `${label} help`,
});
const scope: Field[] = [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  option("result", "add", ["replace", "add"]),
  { name: "suffix", label: "Suffix", type: "string", default: null, has_default: true, nullable: true },
];
const step = (id: string, fields: Field[]): PipelineComponent => ({
  id, kind: "transform", label: id, description: "", input_type: "features", output_type: "features", fields,
});
const accumulate = step("prepare.accumulate", [
  ...scope, option("function", "sum", ["sum", "min", "max", "count"]), text("reset_when", "Reset when"),
]);
const hold = step("prepare.hold", [...scope, text("update_when", "Update when", true)]);
const relation = step("prepare.relation", [
  ...scope, text("against", "Against", true),
  option("statistic", "correlation", ["correlation", "covariance", "slope", "residual"]),
  { name: "window_size", label: "Window", type: "integer", default: 60, has_default: true },
]);
const calculate = step("prepare.calculate", [text("formulas", "Formulas", true)]);

const node = (component: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: component.id, params });
const definition = normalizeDefinition({ input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [] });
const summary = (component: PipelineComponent, params?: PipelineNode["params"]) =>
  nodeSummary(node(component, params), component, definition);

type Issue = { path: string[]; message: string; fix?: { start: number; end: number; text: string } };
function panel(component: PipelineComponent, params: PipelineNode["params"], issues: Issue[] = []) {
  const changes: Record<string, JsonValue>[] = [];
  render(<PipelineFormula node={node(component, params)} component={component} features={["dc_voltage", "dc-current"]}
    featureLabels={{ dc_voltage: "DC voltage" }} issues={issues} onChange={(next) => { changes.push(next); }} />);
  return changes;
}

/** Put the caret into the text, as typing there leaves it. */
function caretAt(name: string, position?: number) {
  const area = screen.getByRole("textbox", { name }) as HTMLTextAreaElement;
  area.focus();
  area.setSelectionRange(position ?? area.value.length, position ?? area.value.length);
  fireEvent.select(area);
  return area;
}
const offered = () => [...document.querySelectorAll("[role=option] code")].map((item) => item.textContent);

describe("steps that read the row, in the composer", () => {
  it("sit in the add-step menu and keep their own controls out of the generic list", () => {
    expect(stepFamily("transform", "prepare.calculate")).toBe("combine");
    expect(stepFamily("transform", "prepare.hold")).toBe("prepare");
    expect(stepFamily("transform", "prepare.relation")).toBe("prepare");
    for (const component of [accumulate, hold, relation, calculate]) expect(stepDescription(component)).not.toBe("");
    const names = (component: PipelineComponent) => stepFields(node(component), component).map((field) => field.name);
    expect(names(accumulate)).toEqual(["function"]);
    expect(names(hold)).toEqual([]);
    expect(names(relation)).toEqual(["statistic", "window_size"]);
    expect(names(calculate)).toEqual([]);
    expect(FORMULA_STEPS.has("prepare.calculate")).toBe(true);
    expect([...CONDITION_STEPS]).toEqual(["prepare.accumulate", "prepare.hold"]);
  });

  it("name added features as core does", () => {
    expect(defaultSuffix(node(accumulate, { function: "count" }), accumulate)).toBe("count");
    expect(defaultSuffix(node(accumulate, { function: "max" }), accumulate)).toBe("running_max");
    expect(defaultSuffix(node(hold), hold)).toBe("held");
    expect(defaultSuffix(node(relation), relation)).toBe("corr60");
    expect(["covariance", "slope", "residual"].map((statistic) =>
      defaultSuffix(node(relation, { statistic, window_size: 30 }), relation))).toEqual(["cov30", "beta30", "resid30"]);
  });

  it("say on the card what they keep, compare and write", () => {
    expect(summary(accumulate, { function: "count" }).text).toBe("Running count since the first accepted observation · Adds *_count");
    expect(summary(accumulate, { reset_when: "dc_current <\n  1" }).text)
      .toBe("Running total · starts over when dc_current < 1 · Adds *_total");
    expect(summary(hold).text).toBe("No condition yet · Adds *_held");
    expect(summary(hold, { update_when: "valid == 1", apply_to: ["dc_voltage"] }))
      .toEqual({ text: "Value from the last time valid == 1", chips: ["+ dc_voltage_held"] });
    expect(summary(relation).text).toBe("No feature to compare with yet · Adds *_corr60");
    expect(summary(relation, { against: "speed", statistic: "residual", window_size: 120 }).text)
      .toBe("Residual against speed over last 120 · Adds *_resid120");
    expect(summary(calculate)).toEqual({ text: "No formula yet" });
    expect(summary(calculate, { formulas: "# power\npower = a * b\nshare = power / total\npower = power / 1000" }))
      .toEqual({ text: "Writes power and share" });
  });
});

describe("the lines of a Calculate step", () => {
  it("are read as name = formula, without notes, comparisons or empty lines", () => {
    expect(writtenNames("power = a * b\n# note = 1\n\n `dc-current` = 2\nflag == 1\nlimit=3\npower = 1"))
      .toEqual(["power", "dc-current", "limit"]);
    const typed = "power = a * b\nshare = po";
    expect(calculateLine(typed, typed.length)).toEqual({ start: 14, naming: false, above: ["power"] });
    expect(calculateLine("power = a\nsha", 13)).toEqual({ start: 10, naming: true, above: ["power"] });
  });

  it("are written without a result or a name of the step", () => {
    const changes = panel(calculate, {});
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Result" })).toBeNull();
    const area = screen.getByRole("textbox", { name: "Formulas" }) as HTMLTextAreaElement;
    expect(area.placeholder).toBe("power = dc_voltage * dc_current");
    expect(area.maxLength).toBe(4096);
    fireEvent.change(area, { target: { value: "power = dc_voltage * 2" } });
    expect(changes).toEqual([{ formulas: "power = dc_voltage * 2" }]);
    expect(screen.getByText("Formulas help")).toBeTruthy();
  });

  it("offer the features written above the caret, and only features for a name", () => {
    panel(calculate, { formulas: "power = dc_voltage * 2\nlater = 1\nshare = po" });
    caretAt("Formulas");
    // The third line reads what the lines above it write.
    expect(offered()).toEqual(["power"]);
    caretAt("Formulas", "power = dc_voltage * 2\nla".length);
    // The second line is still naming its feature, and no feature that arrives starts with la.
    expect(offered()).toEqual([]);
  });

  it("offer the features that arrive as names to replace, without functions", () => {
    panel(calculate, { formulas: "d" });
    caretAt("Formulas");
    expect(offered()).toEqual(["dc_voltage", "`dc-current`"]);
  });

  it("know the condition of an if on the line being written", () => {
    panel(calculate, { formulas: "flag = if(dc_voltage > 1, 1, 0)\nboth = if(flag == 1 an" });
    caretAt("Formulas");
    expect(offered()).toEqual(["and"]);
  });

  it("fix a misspelt name where it stands in the text", () => {
    const formulas = "power = dc_voltage * 2\nshare = powr / 3";
    const changes = panel(calculate, { formulas }, [{
      path: ["formulas"], message: "Line 2: Unknown feature powr at character 9. Did you mean power?",
      fix: { start: 31, end: 35, text: "power" },
    }]);
    expect(screen.getByRole("alert").textContent).toContain("Line 2: Unknown feature powr");
    fireEvent.click(screen.getByRole("button", { name: "Use power" }));
    expect(changes).toEqual([{ formulas: "power = dc_voltage * 2\nshare = power / 3" }]);
    // The features the lines write can be inserted like the ones that arrive.
    expect(screen.getByRole("button", { name: "Insert power" })).toBeTruthy();
  });
});

describe("the condition of a step that works on each feature", () => {
  it("is left out when an Accumulate never starts over", () => {
    const changes = panel(accumulate, { function: "count", reset_when: "dc_voltage < 1" });
    const area = screen.getByRole("textbox", { name: "Reset when" }) as HTMLTextAreaElement;
    expect(area.placeholder).toBe("dc_current < 1");
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    fireEvent.change(area, { target: { value: "" } });
    expect(changes).toEqual([{ function: "count" }]);
    expect(screen.getByText("Reset when help")).toBeTruthy();
  });

  it("offers and, or and not, and shows its problem beside it", () => {
    panel(hold, { update_when: "dc_voltage > 1 o" },
      [{ path: ["update_when"], message: "Unknown feature o at character 16." }]);
    const area = caretAt("Update when");
    expect(offered()).toEqual(["or", "dc_voltage"]);
    expect(area.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Unknown feature o at character 16.");
  });

  it("keeps a Hold's empty condition, so the step says one is needed", () => {
    const changes = panel(hold, { update_when: "a" });
    fireEvent.change(screen.getByRole("textbox", { name: "Update when" }), { target: { value: "" } });
    expect(changes).toEqual([{ update_when: "" }]);
  });
});

describe("the feature a Rolling relation compares with", () => {
  function against(params: PipelineNode["params"], issues: Issue[] = []) {
    const changes: Record<string, JsonValue>[] = [];
    render(<PipelineAgainst node={node(relation, params)} features={["dc_voltage", "dc-current", "speed"]}
      featureLabels={{ dc_voltage: "DC voltage" }} issues={issues} onChange={(next) => { changes.push(next); }} />);
    return changes;
  }

  it("is chosen from the features that arrive", () => {
    const changes = against({});
    const select = screen.getByRole("combobox", { name: "Against" }) as HTMLSelectElement;
    expect([...select.options].map((item) => item.textContent))
      .toEqual(["Choose a feature", "DC voltage", "dc-current", "speed"]);
    fireEvent.change(select, { target: { value: "speed" } });
    expect(changes).toEqual([{ against: "speed" }]);
  });

  it("leaves the features the step uses, since it is compared with them", () => {
    const changes = against({ against: "speed", apply_to: ["dc_voltage", "dc-current"] });
    fireEvent.change(screen.getByRole("combobox", { name: "Against" }), { target: { value: "dc-current" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Against" }), { target: { value: "" } });
    expect(changes).toEqual([
      { against: "dc-current", apply_to: ["dc_voltage"] },
      { apply_to: ["dc_voltage", "dc-current"] },
    ]);
  });

  it("keeps a feature that no longer arrives listed, with its problem", () => {
    against({ against: "torque" }, [{ path: ["against"], message: "torque is not available at this step." }]);
    const select = screen.getByRole("combobox", { name: "Against" }) as HTMLSelectElement;
    expect(select.value).toBe("torque");
    expect(select.selectedOptions[0]?.textContent).toBe("torque (not available here)");
    expect(select.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("torque is not available at this step.");
  });
});
