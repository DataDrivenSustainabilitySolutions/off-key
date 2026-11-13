import { describe, expect, it } from "vitest";
import {
  copySteps, duplicateSteps, fragmentSize, heldSteps, holdSteps, pastedNote, pasteSteps, readSteps, renameFeature,
} from "@/features/pipelines/clipboard";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import type { GraphDocument } from "@/features/pipelines/model";
import { NODE_SIZE, switchedOff } from "@/features/pipelines/semantics";
import { switchOff } from "@/features/pipelines/stepSwitch";

const components = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features" },
    { id: "features.scale", kind: "transform", group: "prepare", label: "Scale", description: "",
      input_type: "features", output_type: "features", fields: [{ name: "factor", label: "Factor", type: "number", default: 1 }] },
    { id: "features.merge", kind: "merge", group: "route", label: "Combine", description: "",
      input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "",
      input_type: "features", output_type: "scores" },
  ],
}).components;

/** Input feeds a scaled and a plain branch, which a combining step joins before the detector. */
const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "features.scale", label: "Triple", params: { factor: 3 } },
      { id: "plain", kind: "transform", component: "features.passthrough" },
      { id: "join", kind: "merge", component: "features.merge" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [
      { source: "input", target: "scale", order: 0 },
      { source: "input", target: "plain", order: 0 },
      // The plain branch is the combining step's first input, though it is listed second.
      { source: "scale", target: "join", order: 1 },
      { source: "plain", target: "join", order: 0 },
      { source: "join", target: "detector", order: 0 },
    ],
  }),
  layout: normalizeLayout({ nodes: {
    input: { x: 0, y: 96 }, scale: { x: 288, y: 0 }, plain: { x: 288, y: 192 },
    join: { x: 576, y: 96 }, detector: { x: 864, y: 96 },
  } }),
});

const empty = (): GraphDocument => ({
  definition: normalizeDefinition({ input_slots: [], nodes: [], edges: [] }),
  layout: normalizeLayout({ nodes: {} }),
});

const place = (document: GraphDocument, id: string) => {
  const { x, y } = document.layout.nodes[id]!;
  return { x, y };
};
const links = (document: GraphDocument) => document.definition.edges.map((edge) => `${edge.source}>${edge.target}#${edge.order}`);

describe("copying steps", () => {
  it("keeps where the steps stand to each other, their settings, titles and the connections among them", () => {
    const fragment = copySteps(design(), ["join", "scale", "plain"])!;
    // In the order of the design, from the upper left corner of the group.
    expect(fragment.steps).toEqual([
      { component: "features.scale", params: { factor: 3 }, label: "Triple", x: 0, y: 0 },
      { component: "features.passthrough", params: {}, x: 0, y: 192 },
      { component: "features.merge", params: {}, x: 288, y: 96 },
    ]);
    // A combining step's inputs come in the order it takes them; connections that leave the group stay behind.
    expect(fragment.links).toEqual([[1, 2], [0, 2]]);
    expect(fragmentSize(fragment)).toEqual({ width: 288 + NODE_SIZE.width, height: 192 + NODE_SIZE.height });
    expect(copySteps(design(), ["gone"])).toBeUndefined();
  });

  it("does not hand out the settings of the design itself", () => {
    const document = design();
    const fragment = copySteps(document, ["scale"])!;
    fragment.steps[0]!.params.factor = 9;
    expect(document.definition.nodes[1]!.params).toEqual({ factor: 3 });
  });
});

describe("pasting steps", () => {
  it("adds the steps at a place and connects them as they were", () => {
    const document = design();
    const result = pasteSteps(document, copySteps(document, ["scale", "plain", "join"])!, components, { x: 0, y: 480 });
    expect(result.skipped).toEqual([]);
    expect(result.ids).toHaveLength(3);
    const [scale, plain, join] = result.ids as [string, string, string];
    expect(place(result.document, scale)).toEqual({ x: 0, y: 480 });
    expect(place(result.document, plain)).toEqual({ x: 0, y: 672 });
    expect(place(result.document, join)).toEqual({ x: 288, y: 576 });
    expect(result.document.definition.nodes.find((node) => node.id === scale)!.params).toEqual({ factor: 3 });
    // The design has a step called Triple, so the copy says that it is one.
    expect(result.document.definition.nodes.find((node) => node.id === scale)!.label).toBe("Triple copy");
    expect(links(result.document).slice(5)).toEqual([`${plain}>${join}#0`, `${scale}>${join}#1`]);
    // The original is as it was.
    expect(links(result.document).slice(0, 5)).toEqual(links(document));
  });

  it("moves down to the first rows where it covers no step", () => {
    const document = design();
    const result = pasteSteps(document, copySteps(document, ["plain"])!, components, { x: 288, y: 0 });
    const at = place(result.document, result.ids[0]!);
    expect(at.x).toBe(288);
    expect(at.y).toBeGreaterThan(192 + NODE_SIZE.height);
  });

  it("leaves out what a design has one of, says why, and keeps the connections whose ends arrived", () => {
    const document = design();
    const fragment = copySteps(document, ["input", "scale", "join", "detector"])!;
    const result = pasteSteps(document, fragment, components, { x: 0, y: 480 });
    expect(result.ids).toHaveLength(2);
    expect(result.skipped).toEqual(["A design has one of these.", "Add another detector from a detector's settings."]);
    const [scale, join] = result.ids as [string, string];
    expect(links(result.document).slice(5)).toEqual([`${scale}>${join}#0`]);
    expect(pastedNote("Pasted", result))
      .toBe("Pasted 2 steps. Left out: A design has one of these. Add another detector from a detector's settings.");
  });

  it("carries a whole design to an empty canvas, under the title each step had", () => {
    const document = design();
    const result = pasteSteps(empty(), copySteps(document, document.definition.nodes.map((node) => node.id))!, components, { x: 0, y: 0 });
    expect(result.skipped).toEqual([]);
    expect(result.document.definition.nodes.map((node) => node.component)).toEqual(document.definition.nodes.map((node) => node.component));
    expect(result.document.definition.edges).toHaveLength(5);
    expect(result.document.definition.nodes[1]!.label).toBe("Triple");
    expect(place(result.document, result.ids[4]!)).toEqual({ x: 864, y: 96 });
  });

  it("leaves out a step this design does not offer", () => {
    const fragment = copySteps(design(), ["scale"])!;
    const result = pasteSteps(empty(), fragment, components.filter((component) => component.id !== "features.scale"), { x: 0, y: 0 });
    expect(result.ids).toEqual([]);
    expect(pastedNote("Pasted", result)).toBe("Nothing was added. Left out: This design does not offer one of the steps.");
  });
});

describe("duplicating steps", () => {
  it("puts the copies under the group, connected to each other only", () => {
    const document = design();
    const result = duplicateSteps(document, ["scale", "join"], components)!;
    const [scale, join] = result.ids as [string, string];
    // Below the lowest of the chosen steps, in the same columns and as far apart.
    expect(place(result.document, scale).x).toBe(288);
    expect(place(result.document, join).x).toBe(576);
    expect(place(result.document, scale).y).toBeGreaterThanOrEqual(96 + NODE_SIZE.height);
    expect(place(result.document, join).y - place(result.document, scale).y).toBe(96);
    expect(links(result.document).slice(5)).toEqual([`${scale}>${join}#0`]);
    expect(pastedNote("Duplicated", result)).toBe("Duplicated 2 steps.");
    expect(pastedNote("Duplicated", { ids: ["one"], skipped: [] })).toBe("Duplicated 1 step.");
    expect(duplicateSteps(document, [], components)).toBeUndefined();
  });
});

describe("duplicating steps that name a feature", () => {
  const formulas = normalizeCatalog({
    catalog_id: "test", authoring_enabled: true, templates: [], components: [
      { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "",
        input_type: null, output_type: "features" },
      { id: "prepare.formula", kind: "transform", group: "prepare", label: "Formula", description: "",
        input_type: "features", output_type: "features", fields: [
          { name: "name", label: "Name", type: "string", default: "formula" },
          { name: "expression", label: "Expression", type: "string", default: "" }] },
      { id: "features.keep", kind: "transform", group: "route", label: "Keep", description: "",
        input_type: "features", output_type: "features", fields: [{ name: "features", label: "Features", type: "features", default: [] }] },
    ],
  }).components;
  const chain = (): GraphDocument => ({
    definition: normalizeDefinition({
      input_slots: [{ id: "voltage", label: "Voltage" }, { id: "current", label: "Current" }],
      nodes: [
        { id: "input", kind: "source", component: "source.aligned" },
        { id: "power", kind: "transform", component: "prepare.formula", params: { name: "power", expression: "voltage * current" } },
        { id: "double", kind: "transform", component: "prepare.formula", params: { name: "double", expression: "power * 2 + power_peak" } },
        { id: "keep", kind: "transform", component: "features.keep", params: { features: ["power", "double"] } },
      ],
      edges: [
        { source: "input", target: "power", order: 0 },
        { source: "power", target: "double", order: 0 },
        { source: "double", target: "keep", order: 0 },
      ],
    }),
    layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, power: { x: 288, y: 0 }, double: { x: 576, y: 0 }, keep: { x: 864, y: 0 } } }),
  });

  it("reads a renamed feature by its new name in the copied steps after it", () => {
    const result = duplicateSteps(chain(), ["power", "double", "keep"], formulas)!;
    const params = result.ids.map((id) => result.document.definition.nodes.find((node) => node.id === id)!.params);
    expect(params).toEqual([
      { name: "power_2", expression: "voltage * current" },
      { name: "double_2", expression: "power_2 * 2 + power_peak" },
      { features: ["power_2", "double_2"] },
    ]);
    // The originals read what they read before.
    expect(result.document.definition.nodes.find((node) => node.id === "double")!.params.expression).toBe("power * 2 + power_peak");
  });

  it("keeps a feature a copied step reads from outside the copy", () => {
    const result = duplicateSteps(chain(), ["double", "keep"], formulas)!;
    const keep = result.document.definition.nodes.find((node) => node.id === result.ids[1])!;
    expect(keep.params.features).toEqual(["power", "double_2"]);
  });

  it("renames where a setting names the feature, a mapping keys it or an expression uses it", () => {
    expect(renameFeature({ target: "a", mapping: { a: "b" }, expression: "`a` + a + ab" }, "a", "a 2"))
      .toEqual({ target: "a 2", mapping: { "a 2": "b" }, expression: "`a 2` + `a 2` + ab" });
  });
});

describe("copying a step that is switched off", () => {
  it("travels as what it was, and arrives switched off", () => {
    const document = switchOff(design(), ["scale"], components);
    const fragment = copySteps(document, ["scale", "plain"])!;
    expect(fragment.steps).toEqual([
      { component: "features.scale", params: { factor: 3 }, label: "Triple", off: true, x: 0, y: 0 },
      // A pass-through step of the design's own is on.
      { component: "features.passthrough", params: {}, x: 0, y: 192 },
    ]);
    // The copy does not hold the settings the design remembers.
    fragment.steps[0]!.params.factor = 9;
    expect(document.layout.switched_off!.scale!.params).toEqual({ factor: 3 });
    fragment.steps[0]!.params.factor = 3;

    const result = pasteSteps(empty(), fragment, components, { x: 0, y: 0 });
    const [scale, plain] = result.document.definition.nodes;
    expect(scale).toMatchObject({ component: "features.passthrough", params: {} });
    expect(switchedOff(result.document.layout, scale)).toEqual({ component: "features.scale", contract_version: 1, params: { factor: 3 } });
    expect(scale!.label).toBe("Triple");
    expect(switchedOff(result.document.layout, plain)).toBeUndefined();
  });

  it("is duplicated switched off, beside the original that stays off", () => {
    const document = switchOff(design(), ["scale"], components);
    const result = duplicateSteps(document, ["scale"], components)!;
    expect(Object.keys(result.document.layout.switched_off!)).toEqual(["scale", result.ids[0]]);
    expect(result.document.layout.switched_off![result.ids[0]!]).toEqual({ component: "features.scale", contract_version: 1, params: { factor: 3 } });
    expect(result.document.layout.switched_off!.scale).toBe(document.layout.switched_off!.scale);
  });

  it("arrives switched on where the design cannot pass features through a step", () => {
    const fragment = copySteps(switchOff(design(), ["scale"], components), ["scale"])!;
    const result = pasteSteps(empty(), fragment, components.filter((component) => component.id !== "features.passthrough"), { x: 0, y: 0 });
    expect(result.document.definition.nodes[0]).toMatchObject({ component: "features.scale", params: { factor: 3 } });
    expect(result.document.layout.switched_off).toBeUndefined();
  });
});

describe("steps on the clipboard", () => {
  it("reads its own text back and takes no other", () => {
    const fragment = copySteps(design(), ["scale", "join"])!;
    const text = holdSteps(fragment);
    expect(readSteps(text)).toEqual(fragment);
    expect(heldSteps()).toBe(fragment);
    expect(readSteps("Triple")).toBeUndefined();
    expect(readSteps('{"format":"aberration-steps"')).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...fragment, schema_version: 2 }))).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...fragment, steps: [] }))).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...fragment, links: [[0, 5]] }))).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...fragment, steps: [{ component: "features.scale", params: null, x: 0, y: 0 }] }))).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...fragment, steps: [{ component: "features.scale", params: {}, x: "0", y: 0 }] }))).toBeUndefined();
    // A step says that it is off, or says nothing.
    const off = { ...fragment, steps: [{ component: "features.scale", params: {}, x: 0, y: 0, off: true }], links: [] };
    expect(readSteps(JSON.stringify(off))).toEqual(off);
    expect(readSteps(JSON.stringify({ ...off, steps: [{ ...off.steps[0], off: false }] }))).toBeUndefined();
    expect(readSteps(JSON.stringify({ ...off, steps: [{ ...off.steps[0], off: "yes" }] }))).toBeUndefined();
  });
});
