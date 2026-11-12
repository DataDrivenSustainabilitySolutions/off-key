import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { changeDetector } from "@/features/pipelines/learning";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { PipelineApart, PipelineScope } from "@/features/pipelines/PipelineScope";
import { stepDescription, stepFamily, stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { JsonValue } from "@/types/monitoring";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

type Field = PipelineComponent["fields"][number];
const fields = (extra: Field[] = []): Field[] => [
  { name: "apply_to", label: "Expected from", type: "features", default: null, has_default: true, nullable: true },
  { name: "result", label: "Result", type: "enum", default: "replace", has_default: true, options: ["replace", "add"] },
  { name: "target", label: "Target", type: "string", required: true, has_default: false },
  { name: "name", label: "Name", type: "string", default: null, has_default: true, nullable: true },
  ...extra,
];
const transform = (id: string, learning: PipelineComponent["learning"], list: Field[]) =>
  ({ id, kind: "transform", label: id, description: "", learning, input_type: "features",
    output_type: "features", fields: list }) as PipelineComponent;
const fitted = transform("static.expected_value", "batch", fields());
const continuous = transform("adaptive.expected_value", "online", fields([
  { name: "forgetting", label: "Forgetting", type: "number", default: 1, has_default: true, maximum: 1, exclusive_minimum: 0 },
]));
const node = (component: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "expect", kind: "transform", component: component.id, params });
const slots = ["current", "flow", "pressure", "temperature"];
const definition = normalizeDefinition({ input_slots: slots.map((id) => ({ id, label: id })), nodes: [] });
const summary = (params: PipelineNode["params"]) => nodeSummary(node(fitted, params), fitted, definition);

type Issue = { path: (string | number)[]; message: string };
function scope(params: PipelineNode["params"], issues: Issue[] = []) {
  const changes: Record<string, JsonValue>[] = [];
  // The inspector leaves the target out of the features to expect it from.
  render(<PipelineScope node={node(fitted, params)} component={fitted}
    features={slots.filter((name) => name !== params.target)} featureLabels={{}} issues={issues}
    onChange={(next) => { changes.push(next); }} />);
  return changes;
}
const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;

describe("an Expected value step", () => {
  it("sits with the steps that reduce features, in both of its forms", () => {
    expect(stepFamily("transform", "static.expected_value")).toBe("reduce");
    expect(stepFamily("transform", "adaptive.expected_value")).toBe("reduce");
    expect(stepDescription(fitted))
      .toBe("Give how far one feature is from what the others imply, by a fit on training data.");
    expect(stepDescription(continuous))
      .toBe("Give how far one feature is from what the others imply, by a fit updated as data arrives.");
  });

  it("lists only the settings without a control of their own", () => {
    expect(stepFields(node(fitted), fitted)).toEqual([]);
    expect(stepFields(node(continuous), continuous).map((field) => field.name)).toEqual(["forgetting"]);
  });

  it("says on its card what it expects and where the residual goes", () => {
    expect(summary({})).toEqual({ text: "No target yet", chips: undefined });
    expect(summary({ target: "current" }))
      .toEqual({ text: "Expects current from the other features · Replaces them with current_residual", chips: undefined });
    expect(summary({ target: "current", apply_to: ["flow", "pressure"], result: "add", name: "load_gap" }))
      .toEqual({ text: "Expects current from flow and pressure", chips: ["+ load_gap"] });
  });

  it("moves to its counterpart with the detector and keeps what it expects", () => {
    const detector = (id: string, learning: PipelineComponent["learning"]) => ({
      id, kind: "detector", label: id, description: "", learning, fields: [], input_type: "features", output_type: "scores",
    }) as PipelineComponent;
    const online = detector("detector:continuous", "online");
    const params = { target: "current", apply_to: ["flow"], result: "add", name: "load_gap" };
    const design = normalizeDefinition({ input_slots: slots.map((id) => ({ id, label: id })),
      nodes: [
        { id: "expect", kind: "transform", component: fitted.id, params },
        { id: "model", kind: "detector", component: "detector:fitted" },
      ],
      edges: [{ source: "expect", target: "model" }] });

    const change = changeDetector(design, "model", online, [fitted, continuous, detector("detector:fitted", "batch"), online]);

    expect(change.converted).toEqual(["expect"]);
    expect(change.definition.nodes[0]).toMatchObject({ component: continuous.id, params: { ...params, forgetting: 1 } });
  });
});

describe("the target of an Expected value", () => {
  function target(params: PipelineNode["params"], issues: Issue[] = []) {
    const changes: Record<string, JsonValue>[] = [];
    render(<PipelineApart field="target" node={node(fitted, params)} features={slots} featureLabels={{}}
      issues={issues} onChange={(next) => { changes.push(next); }} />);
    return changes;
  }

  it("is chosen from the features that arrive", () => {
    const changes = target({});
    const select = screen.getByRole("combobox", { name: "Target" }) as HTMLSelectElement;
    expect([...select.options].map((item) => item.textContent)).toEqual(["Choose a feature", ...slots]);
    expect(screen.getByText("The feature the step expects from the features below. It gives the target minus the expected value."))
      .toBeTruthy();
    fireEvent.change(select, { target: { value: "current" } });
    expect(changes).toEqual([{ target: "current" }]);
  });

  it("leaves the features it is expected from", () => {
    const changes = target({ target: "current", apply_to: ["flow", "pressure"] });
    fireEvent.change(screen.getByRole("combobox", { name: "Target" }), { target: { value: "flow" } });
    expect(changes).toEqual([{ target: "flow", apply_to: ["pressure"] }]);
  });

  it("shows what is wrong with it beside the choice", () => {
    target({}, [{ path: ["target"], message: "Enter a value." }]);
    expect(screen.getByRole("combobox", { name: "Target" }).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Enter a value.");
  });
});

describe("what an Expected value is expected from", () => {
  it("is every other feature until some are chosen", () => {
    const changes = scope({ target: "current" });
    expect(screen.getByRole("group", { name: "Expected from" })).toBeTruthy();
    expect(screen.getByText("Every other feature that arrives")).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "current" })).toBeNull();
    expect(screen.getByText("Replaces every feature with current_residual.")).toBeTruthy();
    fireEvent.click(box("temperature"));
    expect(changes).toEqual([{ target: "current", apply_to: ["flow", "pressure"] }]);
  });

  it("replaces the target and the chosen features, or keeps every feature", () => {
    const { unmount } = render(<PipelineScope node={node(fitted, { target: "current", apply_to: ["flow", "pressure"] })}
      component={fitted} features={slots.slice(1)} featureLabels={{}} issues={[]} onChange={() => {}} />);
    expect(screen.getByText("2 features of 3")).toBeTruthy();
    expect(screen.getByText("Replaces current, flow and pressure with current_residual.")).toBeTruthy();
    unmount();
    scope({ target: "current", result: "add", name: "load_gap" });
    expect(screen.getByRole("button", { name: "Keep features" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Keeps every feature and adds load_gap.")).toBeTruthy();
  });

  it("needs one feature at least", () => {
    scope({ target: "current", apply_to: ["flow"] });
    expect(box("flow").disabled).toBe(true);
    expect(box("pressure").disabled).toBe(false);
  });

  it("names the residual after the target unless a name is given", () => {
    const changes = scope({ target: "current" });
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;
    expect(name.placeholder).toBe("current_residual");
    expect(screen.getByText("The computed feature, in letters, digits and underscores. Leave empty for current_residual."))
      .toBeTruthy();
    fireEvent.change(name, { target: { value: "load_gap" } });
    expect(changes).toEqual([{ target: "current", name: "load_gap" }]);
  });

  it("asks for the target first", () => {
    scope({}, [{ path: ["name"], message: "flow already exists. Choose another name." }]);
    expect(screen.getByText("Choose a target to see what the step gives.")).toBeTruthy();
    // The residual has no name to show before its target is known.
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
  });
});

describe("an Expected value in the inspector", () => {
  const document = (component: PipelineComponent, params: PipelineNode["params"]) => ({
    definition: normalizeDefinition({
      input_slots: slots.map((id) => ({ id, label: id })),
      nodes: [
        { id: "input", kind: "source", component: "source.aligned" },
        { id: "expect", kind: "transform", component: component.id, params },
      ],
      edges: [{ source: "input", target: "expect" }],
    }),
    layout: normalizeLayout(),
  });
  const source = { id: "source.aligned", kind: "source", label: "Aligned inputs", description: "",
    input_type: null, output_type: "features", fields: [] } as PipelineComponent;
  function inspector(component: PipelineComponent, params: PipelineNode["params"], issues: Issue[] = []) {
    const current = document(component, params);
    render(<PipelineInspector document={current} selected="expect" onSelect={() => {}} onChange={() => {}}
      catalog={{ catalog_id: "expected", authoring_enabled: true, components: [source, fitted, continuous], templates: [] }}
      validation={{ valid: !issues.length, definition: current.definition, provenance_complete: true,
        issues: issues.map((issue) => ({ node_id: "expect", code: "scope", message: issue.message, parameter_path: issue.path })),
        features: { input: slots.map((name) => ({ name, slots: [name] })) } }} />);
  }

  it("asks for the target, then for the features it is expected from", () => {
    inspector(continuous, { target: "current" });
    const target = screen.getByRole("combobox", { name: "Target" }) as HTMLSelectElement;
    const group = screen.getByRole("group", { name: "Expected from" });
    expect(target.value).toBe("current");
    expect(target.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The target is not among the features it is expected from.
    expect(screen.getAllByRole("checkbox").map((item) => item.parentElement?.textContent))
      .toEqual(["flow", "pressure", "temperature"]);
    // Target and Name have their own controls; how fast the fit forgets is listed below.
    expect(screen.getAllByRole("textbox", { name: "Name" })).toHaveLength(1);
    expect(screen.queryByRole("textbox", { name: "Target" })).toBeNull();
    expect(screen.getByRole("spinbutton", { name: "Forgetting" })).toBeTruthy();
  });

  it("shows a missing target beside the choice, not as a step error", () => {
    inspector(fitted, {}, [{ path: ["target"], message: "Enter a value." }]);
    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual(["Enter a value."]);
    expect(screen.getByRole("combobox", { name: "Target" }).getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByRole("spinbutton", { name: "Forgetting" })).toBeNull();
  });
});
