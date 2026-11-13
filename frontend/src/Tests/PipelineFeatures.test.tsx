import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineComponent,
  type PipelineValidation,
} from "@/features/pipelines/contracts";
import {
  addForFeature,
  afterGate,
  featuresView,
  rangeText,
  readyText,
  rowPlacement,
  rowSteps,
} from "@/features/pipelines/features";
import { pipelinesApi } from "@/features/pipelines/api";
import type { GraphDocument } from "@/features/pipelines/model";
import { PipelineFeatures } from "@/features/pipelines/PipelineFeatures";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { groupOf } from "./support/fixtures/pipelines";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

type Field = PipelineComponent["fields"][number];
const scoped: Field[] = [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  { name: "result", label: "Result", type: "enum", default: "replace", has_default: true, options: ["replace", "add"] },
];
const component = (id: string, kind: PipelineComponent["kind"], fields: Field[] = [], label = id,
  group = groupOf(kind)): PipelineComponent => ({
  id, kind, group, label, description: "", fields,
  input_type: kind === "source" ? null : kind === "policy" ? "scores" : kind === "output" ? "decisions" : "features",
  output_type: kind === "detector" ? "scores" : kind === "policy" ? "decisions" : kind === "output" ? "evidence" : "features",
});
const components = [
  component("source.aligned", "source", [], "Input"),
  component("prepare.smooth", "transform", scoped, "Smooth"),
  component("prepare.change", "transform", scoped, "Change"),
  component("prepare.range", "transform", scoped, "Range check"),
  component("prepare.formula", "transform", [], "Formula", "combine"),
  component("prepare.gate", "transform", [], "Gate", "route"),
  component("prepare.mute", "transform", [], "Mute alarms", "route"),
  component("adaptive.standard_scaler", "transform", scoped, "Standard scaling", "normalize"),
  component("features.select", "transform", [], "Select", "route"),
  component("features.merge", "merge", [], "Merge"),
  component("detector:aberrant_moving_mahalanobis_distance", "detector", [], "Mahalanobis"),
  component("policy.quantile", "policy", [], "Quantile"),
  component("output.evidence", "output", [], "Evidence"),
];

const tail = [
  { id: "model", kind: "detector", component: "detector:aberrant_moving_mahalanobis_distance" },
  { id: "policy", kind: "policy", component: "policy.quantile" },
  { id: "output", kind: "output", component: "output.evidence" },
] as const;
const document = (nodes: object[], edges: object[]): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: ["a", "b", "c"].map((id) => ({ id, label: `Reading ${id.toUpperCase()}` })),
    nodes: [{ id: "input", kind: "source", component: "source.aligned" }, ...nodes, ...tail] as never,
    edges: [...edges, { source: "model", target: "policy" }, { source: "policy", target: "output" }] as never,
  }),
  layout: normalizeLayout({}),
});
const transform = (id: string, step: string, params = {}) => ({ id, kind: "transform", component: step, params });

// What the compiler reports for these designs, copied from core.
const chain = document([
  transform("smooth", "prepare.smooth", { apply_to: ["a"] }),
  transform("change", "prepare.change", { apply_to: ["b"], result: "add" }),
  transform("clip", "prepare.range", { apply_to: ["c"], low: 0, high: 5 }),
  transform("power", "prepare.formula", { expression: "a * c", name: "power" }),
  transform("scale", "adaptive.standard_scaler", { apply_to: ["a", "power"] }),
], ["input:smooth", "smooth:change", "change:clip", "clip:power", "power:scale", "scale:model"]
  .map((pair) => { const [source, target] = pair.split(":"); return { source, target }; }));
const chainReport = {
  features: {
    input: [{ name: "a", slots: ["a"] }, { name: "b", slots: ["b"] }, { name: "c", slots: ["c"] }],
    smooth: [{ name: "a", slots: ["a"], previous: "input.a", steps: ["smooth"] }, { name: "b", slots: ["b"], previous: "input.b" }, { name: "c", slots: ["c"], previous: "input.c" }],
    change: [{ name: "a", slots: ["a"], previous: "smooth.a", steps: ["smooth"] }, { name: "b", slots: ["b"], previous: "smooth.b" }, { name: "c", slots: ["c"], previous: "smooth.c" }, { name: "b_diff1", slots: ["b"], previous: "smooth.b", steps: ["change"] }],
    clip: [{ name: "a", slots: ["a"], previous: "change.a", steps: ["smooth"] }, { name: "b", slots: ["b"], previous: "change.b" }, { name: "c", slots: ["c"], minimum: 0, maximum: 5, previous: "change.c", steps: ["clip"] }, { name: "b_diff1", slots: ["b"], previous: "change.b_diff1", steps: ["change"] }],
    power: [{ name: "a", slots: ["a"], previous: "clip.a", steps: ["smooth"] }, { name: "b", slots: ["b"], previous: "clip.b" }, { name: "c", slots: ["c"], minimum: 0, maximum: 5, previous: "clip.c", steps: ["clip"] }, { name: "b_diff1", slots: ["b"], previous: "clip.b_diff1", steps: ["change"] }, { name: "power", slots: ["a", "c"], steps: ["power"] }],
    scale: [{ name: "a", slots: ["a"], previous: "power.a", steps: ["smooth", "scale"] }, { name: "b", slots: ["b"], previous: "power.b" }, { name: "c", slots: ["c"], minimum: 0, maximum: 5, previous: "power.c", steps: ["clip"] }, { name: "b_diff1", slots: ["b"], previous: "power.b_diff1", steps: ["change"] }, { name: "power", slots: ["a", "c"], previous: "power.power", steps: ["power", "scale"] }],
  },
} as unknown as PipelineValidation;

const branched = document([
  transform("pick_a", "features.select", { features: ["a"] }),
  transform("scale", "adaptive.standard_scaler"),
  transform("pick_b", "features.select", { features: ["b"] }),
  { id: "merge", kind: "merge", component: "features.merge" },
], [
  { source: "input", target: "pick_a" }, { source: "pick_a", target: "scale" }, { source: "input", target: "pick_b" },
  { source: "scale", target: "merge", order: 0 }, { source: "pick_b", target: "merge", order: 1 },
  { source: "merge", target: "model" },
]);
const branchedReport = {
  features: {
    input: [{ name: "a", slots: ["a"] }, { name: "b", slots: ["b"] }, { name: "c", slots: ["c"] }],
    pick_a: [{ name: "a", slots: ["a"], previous: "input.a" }],
    pick_b: [{ name: "b", slots: ["b"], previous: "input.b" }],
    scale: [{ name: "a", slots: ["a"], previous: "pick_a.a", steps: ["scale"] }],
    merge: [{ name: "a", slots: ["a"], previous: "scale.a", steps: ["scale"] }, { name: "b", slots: ["b"], previous: "pick_b.b" }],
  },
} as unknown as PipelineValidation;

const find = (id: string) => components.find((item) => item.id === id)!;
const row = (view: ReturnType<typeof featuresView>, name: string) => view.rows.find((item) => item.name === name)!;

describe("the Features view", () => {
  it("lists what the detector receives: readings in order, their added features with them, then derived ones", () => {
    const view = featuresView(chain.definition, chainReport);
    expect(view.rows.map((item) => [item.name, item.reading, item.steps])).toEqual([
      ["a", "a", ["smooth", "scale"]],
      ["b", "b", []],
      ["b_diff1", "b", ["change"]],
      ["c", "c", ["clip"]],
      ["power", undefined, ["power", "scale"]],
    ]);
    expect(row(view, "c")).toMatchObject({ minimum: 0, maximum: 5 });
    expect(view.unused).toEqual([]);
    expect(view.complete).toBe(true);
    // A reading no feature comes from is named, so a dropped one is not missed.
    expect(featuresView(branched.definition, branchedReport).unused).toEqual(["c"]);
  });

  it("places a Prepare step before the first learned step, under the feature's name there", () => {
    const view = featuresView(chain.definition, chainReport);
    expect(rowPlacement(chain.definition, chainReport, components, view, row(view, "a"), find("prepare.smooth")))
      .toEqual({ link: { source: "power", target: "scale" }, feature: "a" });
    // The scaler uses only a and power, but b_diff1 passes it, so the step goes before it too.
    expect(rowPlacement(chain.definition, chainReport, components, view, row(view, "b_diff1"), find("prepare.range")))
      .toEqual({ link: { source: "power", target: "scale" }, feature: "b_diff1" });
    // Without a learned step on the way, it goes just before the detector.
    const plain = document([transform("smooth", "prepare.smooth")],
      [{ source: "input", target: "smooth" }, { source: "smooth", target: "model" }]);
    const report = { features: { input: chainReport.features.input,
      smooth: [{ name: "a", slots: ["a"], previous: "input.a", steps: ["smooth"] }] } } as unknown as PipelineValidation;
    const flat = featuresView(plain.definition, report);
    expect(rowPlacement(plain.definition, report, components, flat, flat.rows[0]!, find("prepare.range")))
      .toEqual({ link: { source: "smooth", target: "model" }, feature: "a" });
    // Learned steps always go just before the detector.
    expect(rowPlacement(chain.definition, chainReport, components, view, row(view, "c"), find("adaptive.standard_scaler")))
      .toEqual({ link: { source: "scale", target: "model" }, feature: "c" });
  });

  it("follows a feature through a merge to its own branch", () => {
    const view = featuresView(branched.definition, branchedReport);
    // b reaches the merge raw, but the merge is after a scaler, so b's step goes on b's branch.
    expect(rowPlacement(branched.definition, branchedReport, components, view, row(view, "b"), find("prepare.smooth")))
      .toEqual({ link: { source: "pick_b", target: "merge" }, feature: "b" });
    expect(rowPlacement(branched.definition, branchedReport, components, view, row(view, "a"), find("prepare.smooth")))
      .toEqual({ link: { source: "pick_a", target: "scale" }, feature: "a" });
  });

  it("refuses a Prepare step for a feature a learned step made", () => {
    const report = {
      features: {
        input: [{ name: "a", slots: ["a"] }],
        pick_a: [{ name: "a", slots: ["a"], previous: "input.a" }],
        scale: [{ name: "pca.component_1", slots: ["a"], steps: ["scale"] }],
        merge: [{ name: "pca.component_1", slots: ["a"], previous: "scale.pca.component_1", steps: ["scale"] }],
      },
    } as unknown as PipelineValidation;
    const view = featuresView(branched.definition, report);
    expect(rowPlacement(branched.definition, report, components, view, view.rows[0]!, find("prepare.smooth")))
      .toEqual({ reason: "pca.component_1 comes from a learned step, and Prepare steps run before anything learns." });
  });

  it("adds the step on that wire, set to that one feature", () => {
    const view = featuresView(chain.definition, chainReport);
    const added = addForFeature(chain, chainReport, components, view, row(view, "a"), find("prepare.smooth"))!;
    const node = added.document.definition.nodes.find((item) => item.id === added.id)!;
    expect(node).toMatchObject({ component: "prepare.smooth", params: { apply_to: ["a"] } });
    expect(added.document.definition.edges).toEqual(expect.arrayContaining([
      { source: "power", target: added.id, order: 0 }, { source: added.id, target: "scale", order: 0 },
    ]));
    expect(rowSteps(chain.definition, components).map((item) => item.id))
      .toEqual(["prepare.smooth", "prepare.change", "prepare.range", "adaptive.standard_scaler"]);
  });

  it("describes ranges and warm-up in words", () => {
    expect([rangeText(0, 1200), rangeText(0, null), rangeText(null, 5), rangeText(2, 2), rangeText()])
      .toEqual(["0 to 1,200", "at least 0", "at most 5", "always 2", undefined]);
    expect(rangeText(-0.000012345, 3.14159)).toBe("-0.00001235 to 3.142");
    expect(readyText(11, false)).toBe("Ready after 11 observations");
    expect(readyText(11, true)).toBe("Ready after at least 11 observations");
    expect(readyText(1, false)).toBe("Ready from the first observation");
    expect(readyText(1, true)).toBe("Ready from the first observation a Gate lets through");
    const gated = document([transform("gate", "prepare.gate", { condition: "a > 1" }), transform("smooth", "prepare.smooth")],
      [{ source: "input", target: "gate" }, { source: "gate", target: "smooth" }, { source: "smooth", target: "model" }]);
    expect([afterGate(gated.definition, "smooth"), afterGate(gated.definition, "gate"), afterGate(gated.definition, "input")])
      .toEqual([true, true, false]);
  });
});

function renderView(props: Partial<Parameters<typeof PipelineFeatures>[0]> = {}) {
  const changes: GraphDocument[] = [];
  const selections: (string | undefined)[] = [];
  render(<PipelineFeatures document={chain} components={components} report={chainReport}
    onSelect={(id) => { selections.push(id); }} onChange={(next) => { changes.push(next); }} {...props} />);
  return { changes, selections };
}

describe("the Features view on screen", () => {
  it("shows each feature's steps as chips that open the step", () => {
    const { selections } = renderView({ selected: "scale" });
    const readings = screen.getByRole("list", { name: "Features from readings" });
    const first = within(readings).getAllByRole("listitem")[0]!;
    expect(first.textContent).toContain("Reading A");
    expect(within(first).getAllByRole("button").map((button) => button.textContent))
      .toEqual(["Smooth", "Standard scaling", ""]);
    expect(within(first).getByRole("button", { name: "Standard scaling" }).getAttribute("aria-current")).toBe("true");
    fireEvent.click(within(first).getByRole("button", { name: "Smooth" }));
    expect(selections).toEqual(["smooth"]);
    // A feature made from several says where it comes from.
    const derived = screen.getByRole("list", { name: "Features made from several" });
    expect(within(derived).getByRole("listitem").textContent).toContain("From Reading A and Reading C");
    expect(screen.getByText("0 to 5")).toBeTruthy();
    expect(screen.getByText("Raw")).toBeTruthy();
  });

  it("adds a step for one feature from its row", () => {
    const { changes, selections } = renderView();
    fireEvent.click(screen.getByRole("button", { name: "Add a step for c" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Smooth" }));
    expect(changes).toHaveLength(1);
    const added = changes[0]!.definition.nodes.find((node) => node.id === selections[0])!;
    expect(added).toMatchObject({ component: "prepare.smooth", params: { apply_to: ["c"] } });
  });

  it("waits for the latest check before adding, and says why the list is empty", () => {
    renderView({ stale: true });
    expect((screen.getByRole("button", { name: "Add a step for a" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Checking the latest changes…");
  });

  it("explains an empty view and leaves out adding when read-only", () => {
    const { unmount } = render(<PipelineFeatures document={chain} components={components}
      onSelect={() => {}} onChange={() => {}} />);
    expect(screen.getByText("The features appear once the graph has been checked.")).toBeTruthy();
    unmount();
    renderView({ readOnly: true });
    expect(screen.queryByRole("button", { name: "Add a step for a" })).toBeNull();
  });

  it("lists the Gates and Mute alarms steps, which decide and change no feature", () => {
    const gated = document([transform("gate", "prepare.gate", { condition: "a > 1" }),
      transform("mute", "prepare.mute", { condition: "b < 100" })],
    [{ source: "input", target: "gate" }, { source: "gate", target: "mute" }, { source: "mute", target: "model" }]);
    const passed = (from: string) => ["a", "b", "c"].map((name) => ({ name, slots: [name], previous: `${from}.${name}` }));
    const report = { features: { input: chainReport.features.input, gate: passed("input"), mute: passed("gate") },
    } as unknown as PipelineValidation;
    const selections: (string | undefined)[] = [];
    render(<PipelineFeatures document={gated} components={components} report={report}
      onSelect={(id) => { selections.push(id); }} onChange={() => {}} />);
    const decisions = within(screen.getByRole("group", { name: "Gates and mutes" }));
    fireEvent.click(decisions.getByRole("button", { name: "Only when a > 1" }));
    fireEvent.click(decisions.getByRole("button", { name: "No alarm while b < 100" }));
    expect(selections).toEqual(["gate", "mute"]);
    // Neither step is a chip in a feature's row.
    expect(decisions.getAllByRole("button")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /Only when|No alarm while/ })).toHaveLength(2);
  });
});

const catalog = { catalog_id: "features", authoring_enabled: true, components, templates: [] };
const checked = { ...chainReport, valid: true, issues: [], definition: chain.definition, provenance_complete: true,
  ready_after: { smooth: 10, change: 11, clip: 11, power: 11 } } as PipelineValidation;

describe("the inspector of a Prepare step", () => {
  it("says when the step first has output and the range of each feature it gives", () => {
    render(<PipelineInspector document={chain} catalog={catalog} selected="clip" validation={checked}
      onSelect={() => {}} onChange={() => {}} />);
    expect(screen.getByText("Ready after 11 observations")).toBeTruthy();
    expect(screen.getByText(/From Reading C · c · 0 to 5/)).toBeTruthy();
  });

  it("says nothing about warm-up for a step the Prepare stage does not run", () => {
    render(<PipelineInspector document={chain} catalog={catalog} selected="scale" validation={checked}
      onSelect={() => {}} onChange={() => {}} />);
    expect(screen.queryByText(/^Ready /)).toBeNull();
  });
});

describe("the Graph and Features switch", () => {
  it("shows the same design as one row per feature", async () => {
    const { PipelineWorkbench } = await import("@/features/pipelines/PipelineWorkbench");
    // The editor reads the block library when it opens; this one never answers.
    vi.spyOn(pipelinesApi, "blocks").mockReturnValue(new Promise(() => {}));
    render(<PipelineWorkbench catalog={catalog} document={chain} validation={checked} onSelect={() => {}}
      onChange={() => {}} onAdd={() => {}} />);
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: "Graph" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(views).getByRole("button", { name: "Features" }));
    expect(screen.getByRole("region", { name: "Features" })).toBeTruthy();
    expect(screen.queryByLabelText("Pipeline graph")).toBeNull();
    fireEvent.click(within(views).getByRole("button", { name: "Graph" }));
    expect(screen.queryByRole("region", { name: "Features" })).toBeNull();
  });
});

describe("a step whose features are unknown", () => {
  const select = component("features.select", "transform", [
    { name: "features", label: "Features", type: "features", required: true, has_default: false },
  ], "Select");
  const rename = component("features.rename", "transform", [
    { name: "mapping", label: "Mapping", type: "rename", required: true, has_default: false },
  ], "Rename features");
  const blocked = document([transform("rename", "features.rename", { mapping: {} }), transform("pick", "features.select")], [
    { source: "input", target: "rename" }, { source: "rename", target: "pick" }, { source: "pick", target: "model" },
  ]);
  const report = {
    valid: false, definition: blocked.definition, provenance_complete: true,
    features: { input: chainReport.features.input },
    issues: [{ code: "parameters", severity: "error", node_id: "rename", parameter_path: ["mapping"], message: "Enter a value." }],
  } as unknown as PipelineValidation;

  it("names the step before it whose problem hides them, and goes there", () => {
    const selections: (string | undefined)[] = [];
    render(<PipelineInspector document={blocked} catalog={{ ...catalog, components: [select, rename, ...components] }}
      selected="pick" validation={report} onSelect={(id) => selections.push(id)} onChange={() => {}} />);
    expect(screen.getByRole("status").textContent).toContain(
      "because Rename features has a problem with Mapping: Enter a value.");
    expect(screen.queryByText("Connect inputs to select available features.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Go to Rename features" }));
    expect(selections).toEqual(["rename"]);
  });
});
