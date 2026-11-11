import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineCatalog,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { presentGraph } from "@/features/pipelines/graphPresentation";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { PipelineScope } from "@/features/pipelines/PipelineScope";
import { hasScope, isWarning, stepScope } from "@/features/pipelines/scope";
import { stepFamily } from "@/features/pipelines/steps";
import { changeDetector } from "@/features/pipelines/learning";
import type { JsonValue } from "@/types/monitoring";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

type Field = PipelineComponent["fields"][number];
const scopeFields = (suffix?: string): Field[] => [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  { name: "result", label: "Result", type: "enum", default: "replace", has_default: true, options: ["replace", "add"] },
  ...(suffix ? [{ name: "suffix", label: "Suffix", type: "string", default: suffix, has_default: true } satisfies Field] : []),
];
const transform = (id: string, learning: PipelineComponent["learning"], fields: PipelineComponent["fields"]) =>
  ({ id, kind: "transform", label: id, description: "", learning, input_type: "features",
    output_type: "features", fields }) as PipelineComponent;

const robust = transform("adaptive.robust_scaler", "online", [
  ...scopeFields("robust"),
  { name: "window_size", label: "Window Size", type: "integer", default: 256, has_default: true },
]);
const staticRobust = transform("static.robust_scaler", "batch", scopeFields("robust"));
const pca = transform("static.pca", "batch", [
  ...scopeFields(),
  { name: "n_components", label: "N Components", type: "integer", default: 1, has_default: true },
]);
const incoming = ["dc_voltage", "dc_current", "temp"];
const labels = { dc_voltage: "DC voltage", dc_current: "DC current" };

function scope(params: PipelineNode["params"], options: {
  component?: PipelineComponent;
  issues?: { path: (string | number)[]; message: string }[];
  readOnly?: boolean;
} = {}) {
  const changes: { params: Record<string, JsonValue>; field: string }[] = [];
  const component = options.component ?? robust;
  render(<PipelineScope node={{ id: "scale", kind: "transform", component: component.id, params }}
    component={component} features={incoming} featureLabels={labels} issues={options.issues ?? []}
    readOnly={options.readOnly} onChange={(next, field) => { changes.push({ params: next, field }); }} />);
  return changes;
}
const box = (name: string | RegExp) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

describe("which features a step uses", () => {
  it("uses every feature that arrives until one is unchecked, then keeps their order", () => {
    const changes = scope({});

    expect(screen.getByText("Every feature that arrives")).toBeTruthy();
    expect(["DC voltage", "DC current", "temp"].map((name) => box(name).checked)).toEqual([true, true, true]);
    fireEvent.click(box("DC current"));

    expect(changes).toEqual([{ params: { apply_to: ["dc_voltage", "temp"] }, field: "apply_to" }]);
  });

  it("keeps at least one feature and returns to every feature once all are checked", () => {
    const one = scope({ apply_to: ["dc_current"] });
    expect(screen.getByText("1 feature of 3")).toBeTruthy();
    // The last feature in use cannot be unchecked.
    expect(box("DC current").disabled).toBe(true);
    fireEvent.click(box("DC voltage"));
    expect(one[0]?.params.apply_to).toEqual(["dc_voltage", "dc_current"]);
  });

  it("drops the choice when the last missing feature is checked again", () => {
    const changes = scope({ apply_to: ["dc_voltage", "dc_current"], result: "add" });

    fireEvent.click(box("temp"));

    expect(changes).toEqual([{ params: { result: "add" }, field: "apply_to" }]);
  });

  it("lists a chosen feature that no longer arrives until it is unchecked", () => {
    const changes = scope({ apply_to: ["dc_voltage", "gone"] });

    const missing = box(/^gone/);
    expect(missing.closest("label")?.textContent).toBe("gone not available here");
    fireEvent.click(missing);

    expect(changes[0]?.params.apply_to).toEqual(["dc_voltage"]);
  });
});

describe("where a step's output goes", () => {
  it("replaces values in place unless asked to add suffixed features", () => {
    const changes = scope({ apply_to: ["dc_voltage"] });
    expect(pressed("Replace values")).toBe("true");
    expect(pressed("Add new features")).toBe("false");
    expect(screen.getByText("Changes the values in place; the names stay the same.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Suffix" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Add new features" }));

    expect(changes).toEqual([{ params: { apply_to: ["dc_voltage"], result: "add" }, field: "result" }]);
  });

  it("names the added features with the suffix, falling back to the step's default", () => {
    const changes = scope({ apply_to: ["dc_voltage", "dc_current"], result: "add" });
    expect(screen.getByText("Keeps the values and adds dc_voltage_robust and dc_current_robust.")).toBeTruthy();
    const suffix = screen.getByRole("textbox", { name: "Suffix" }) as HTMLInputElement;
    expect(suffix.placeholder).toBe("robust");

    fireEvent.change(suffix, { target: { value: "iqr" } });
    fireEvent.click(screen.getByRole("button", { name: "Replace values" }));

    expect(changes.map((change) => [change.field, change.params.suffix, change.params.result]))
      .toEqual([["suffix", "iqr", "add"], ["result", undefined, undefined]]);
  });

  it("clears a typed suffix back to the default", () => {
    const changes = scope({ result: "add", suffix: "iqr" });
    expect(screen.getByText(/adds dc_voltage_iqr, dc_current_iqr and temp_iqr\.$/)).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Suffix" }), { target: { value: "" } });

    expect(changes[0]?.params).toEqual({ result: "add" });
  });

  it("speaks of components for a projection, which has no suffix", () => {
    scope({ apply_to: ["dc_voltage", "dc_current"], n_components: 2 }, { component: pca });
    expect(pressed("Replace features")).toBe("true");
    expect(screen.getByText("Replaces DC voltage and DC current with 2 components.")).toBeTruthy();
  });

  it("keeps the inputs of a projection that adds its components", () => {
    scope({ result: "add", n_components: 3 }, { component: pca });
    expect(pressed("Keep features")).toBe("true");
    expect(screen.getByText("Keeps every feature and adds 3 components.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Suffix" })).toBeNull();
  });

  it("shows the compiler's scope errors beside the controls they concern", () => {
    scope({ result: "add" }, { issues: [
      { path: ["apply_to"], message: "gone is not available at this step." },
      { path: ["suffix"], message: "dc_voltage_robust already exists. Choose another suffix." },
    ] });

    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual([
      "gone is not available at this step.",
      "dc_voltage_robust already exists. Choose another suffix.",
    ]);
    expect(screen.getByRole("textbox", { name: "Suffix" }).getAttribute("aria-invalid")).toBe("true");
  });

  it("changes nothing while read-only", () => {
    scope({ result: "add" }, { readOnly: true });
    for (const control of [...screen.getAllByRole("checkbox"), ...screen.getAllByRole("button")])
      expect((control as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("textbox", { name: "Suffix" }) as HTMLInputElement).disabled).toBe(true);
  });
});

describe("scope settings", () => {
  it("reads the compiler's defaults and the catalog's suffix", () => {
    const node = (params: PipelineNode["params"]): PipelineNode =>
      ({ id: "scale", kind: "transform", component: robust.id, params });
    expect(hasScope(robust)).toBe(true);
    expect(hasScope(transform("features.select", "none", []))).toBe(false);
    expect(stepScope(node({ apply_to: null, result: "replace", suffix: "robust" }), robust))
      .toEqual({ applyTo: undefined, add: false, suffix: "robust", elementwise: true });
    expect(stepScope(node({ result: "add", suffix: "" }), robust)?.suffix).toBe("robust");
    expect(stepScope(node({}), pca)).toEqual({ applyTo: undefined, add: false, suffix: undefined, elementwise: false });
    expect(isWarning({ severity: "warning" })).toBe(true);
    // Issues from before severities existed are errors.
    expect(isWarning({})).toBe(false);
  });

  it("puts robust scaling with the other normalizing steps", () => {
    expect(stepFamily("transform", "static.robust_scaler")).toBe("normalize");
    expect(stepFamily("transform", "adaptive.robust_scaler")).toBe("normalize");
  });

  it("keeps a step's scope when it moves to its counterpart with the detector", () => {
    const detector = (id: string, learning: PipelineComponent["learning"]) => ({
      id, kind: "detector", label: id, description: "", learning, fields: [], input_type: "features", output_type: "scores",
    }) as PipelineComponent;
    const continuous = detector("detector:continuous", "online");
    const scope = { apply_to: ["dc_voltage"], result: "add", suffix: "iqr" };
    const definition = normalizeDefinition({ input_slots: [{ id: "dc_voltage", label: "" }],
      nodes: [
        { id: "scale", kind: "transform", component: "static.robust_scaler", params: scope },
        { id: "model", kind: "detector", component: "detector:fitted" },
      ],
      edges: [{ source: "scale", target: "model" }] });

    const change = changeDetector(definition, "model", continuous,
      [staticRobust, robust, detector("detector:fitted", "batch"), continuous]);

    expect(change.converted).toEqual(["scale"]);
    expect(change.definition.nodes[0]).toMatchObject({
      component: "adaptive.robust_scaler", params: { ...scope, window_size: 256 },
    });
  });
});

describe("warnings", () => {
  const document = () => ({
    definition: normalizeDefinition({
      input_slots: [{ id: "dc_voltage", label: "DC voltage" }, { id: "dc_current", label: "dc_current" }],
      nodes: [
        { id: "input", kind: "source", component: "source.aligned" },
        { id: "scale", kind: "transform", component: robust.id, params: { apply_to: ["dc_voltage"] } },
      ],
      edges: [{ source: "input", target: "scale" }],
    }),
    layout: normalizeLayout(),
  });
  const source = { id: "source.aligned", kind: "source", label: "Aligned inputs", description: "",
    input_type: null, output_type: "features", fields: [] } as PipelineComponent;
  const warning = { node_id: "scale", code: "unused", message: "dc_current is not used after this step.",
    severity: "warning" as const };

  it("counts a step's warnings apart from the errors that block it", () => {
    const graph = presentGraph(document(), [source, robust], {}, [
      warning,
      { node_id: "scale", code: "parameter", message: "Too small", parameter_path: ["window_size"] },
    ]);
    expect(graph.nodes.find((node) => node.id === "scale")?.data).toMatchObject({ issueCount: 1, warningCount: 1 });
  });

  it("lists a warning as status beside the scope editor, never as an alert", () => {
    render(<PipelineInspector document={document()} selected="scale" onSelect={() => {}} onChange={() => {}}
      catalog={{ catalog_id: "scope", authoring_enabled: true, components: [source, robust], templates: [] }}
      validation={{ valid: true, definition: document().definition, issues: [warning], provenance_complete: true,
        features: { input: [{ name: "dc_voltage", slots: ["dc_voltage"] }, { name: "dc_current", slots: ["dc_current"] }] } }} />);

    expect(screen.getByRole("status").textContent).toBe("dc_current is not used after this step.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("group", { name: "Applies to" })).toBeTruthy();
    // The inspector names a reading by its label and its key.
    expect(box("DC voltage · dc_voltage").checked).toBe(true);
    expect(box("dc_current").checked).toBe(false);
    // The scope settings appear once, above the step's own settings.
    expect(screen.queryByRole("combobox", { name: "Result" })).toBeNull();
    expect(screen.getByRole("spinbutton", { name: "Window Size" })).toBeTruthy();
  });

  it("keeps the features to choose from while an edit is checked", () => {
    const checked = { valid: true, definition: document().definition, issues: [warning], provenance_complete: true,
      features: { input: [{ name: "dc_voltage", slots: ["dc_voltage"] }, { name: "dc_current", slots: ["dc_current"] }] } };
    render(<PipelineInspector document={document()} selected="scale" onSelect={() => {}} onChange={() => {}}
      catalog={{ catalog_id: "scope", authoring_enabled: true, components: [source, robust], templates: [] }}
      lastValidation={checked} />);

    expect(box("dc_current").checked).toBe(false);
    expect(screen.queryByText("not available here")).toBeNull();
    // A finding from before the edit is not repeated as if it were current.
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("calls a design with only warnings complete and names them in the status chip", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    const catalog: PipelineCatalog = { catalog_id: "scope", authoring_enabled: true, templates: [],
      components: [source, robust] };
    render(<PipelineWorkbench catalog={catalog} document={document()} onSelect={() => {}} onChange={() => {}}
      onAdd={() => {}} validation={{ valid: true, definition: document().definition, issues: [warning], features: {},
        provenance_complete: true }} />);

    fireEvent.click(screen.getByRole("button", { name: "Design is complete, 1 warning" }));

    expect(screen.getByRole("heading", { name: "Design is complete" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Warning: dc_current is not used after this step." })).toBeTruthy();
    expect(screen.queryByText("Every step is connected and set up.")).toBeNull();
  });
});
