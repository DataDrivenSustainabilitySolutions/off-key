import { describe, expect, it, vi } from "vitest";
import { normalizeDefinition, normalizeLayout, type PipelineComponent, type PipelineValidation } from "@/features/pipelines/contracts";
import { designFileName, MAX_DESIGN_BYTES, openDesign, openDesignFile, writeDesign } from "@/features/pipelines/designFile";
import type { GraphDocument } from "@/features/pipelines/model";
import { switchOff } from "@/features/pipelines/stepSwitch";
import { ApiRequestError } from "@/lib/api-client";
import { DESIGN_FILE, type PipelineDefinition, type PipelineDesignFile } from "@/types/pipelines.generated";

// Arranging stands every card in a row, so a test can tell it happened.
vi.mock("@/features/pipelines/layout", () => ({
  arrangeGraph: vi.fn(async (definition: PipelineDefinition, layout: ReturnType<typeof normalizeLayout>) => ({
    ...layout,
    nodes: Object.fromEntries((definition.nodes ?? []).map((node, index) => [node.id, { ...layout.nodes[node.id], x: 300 * index, y: 40 }])),
  })),
}));
vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { validate: vi.fn() } }));

const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "smooth", kind: "transform", component: "prepare.smooth", label: "Calm it down", params: { window: 10 } },
    ],
    edges: [{ source: "input", target: "smooth", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 96 }, smooth: { x: 288, y: 96 }, gone: { x: 900, y: 0 } } }),
});

/** The server's reading of a definition: the same design. */
const check = vi.fn(async (definition: PipelineDefinition): Promise<PipelineValidation> => ({
  valid: true, issues: [], features: {}, definition: normalizeDefinition(definition),
}));
const file = (change: Record<string, unknown> = {}) =>
  JSON.stringify({ format: DESIGN_FILE.format, schema_version: 1, name: "Charger health", definition: design().definition, ...change });

describe("a design as a file", () => {
  it("writes the name, the description, the steps and the places of their cards", () => {
    const document = design();
    const written = JSON.parse(writeDesign(document, "  Charger health ", "Watches the DC side.\n")) as PipelineDesignFile;
    expect(written).toEqual({
      $schema: "https://docs.aberration.app/reference/design-file.schema.json",
      format: "aberration-design", schema_version: 1,
      name: "Charger health", description: "Watches the DC side.",
      definition: document.definition,
      // A place a removed step left behind is not written.
      layout: { nodes: { input: { x: 0, y: 96 }, smooth: { x: 288, y: 96 } } },
    });
    expect(written.definition.nodes![1]!.label).toBe("Calm it down");
    expect(writeDesign(document, "", "").endsWith("}\n")).toBe(true);
  });

  it("names the file after the design", () => {
    expect(designFileName("Charger health")).toBe("charger-health.design.json");
    expect(designFileName("  Größe / Übersicht (v2)  ")).toBe("größe-übersicht-v2.design.json");
    expect(designFileName("")).toBe("design.design.json");
    expect(designFileName("x".repeat(200))).toBe(`${"x".repeat(60)}.design.json`);
  });

  it("opens what it wrote", async () => {
    const document = design();
    const opened = await openDesign(writeDesign(document, "Charger health", "Watches the DC side."), check);
    expect(check).toHaveBeenLastCalledWith(document.definition);
    expect(opened).toEqual({
      name: "Charger health", description: "Watches the DC side.",
      document: { definition: document.definition,
        layout: normalizeLayout({ nodes: { input: { x: 0, y: 96 }, smooth: { x: 288, y: 96 } } }) },
    });
  });

  it("takes the definition as the server reads it", async () => {
    const current = normalizeDefinition({ nodes: [{ id: "input", kind: "source", component: "source.aligned" }] });
    const opened = await openDesign(file({ definition: { schema_version: 2, nodes: [] } }),
      async () => ({ valid: false, issues: [], features: {}, definition: current }));
    expect(opened.document.definition).toBe(current);
  });

  it("arranges a design whose file does not place every step", async () => {
    const opened = await openDesign(file({ layout: { nodes: { smooth: { x: 12, y: 34 }, input: { x: "0", y: 0 } } } }), check);
    expect(opened.document.definition.nodes.map((node) => node.label)).toEqual([undefined, "Calm it down"]);
    expect(opened.document.layout.nodes).toEqual({ input: { x: 0, y: 40 }, smooth: { x: 300, y: 40 } });
    // No layout at all is the same case.
    expect((await openDesign(file(), check)).document.layout.nodes).toEqual({ input: { x: 0, y: 40 }, smooth: { x: 300, y: 40 } });
  });

  it("writes what a switched-off step was, and opens it switched off", async () => {
    const stand = [{ id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "",
      input_type: "features", output_type: "features", fields: [] }] as unknown as PipelineComponent[];
    const document = switchOff(design(), ["smooth"], stand);
    // What the layout remembers of a step that is on, or gone, is not written.
    document.layout.switched_off!.input = { component: "source.other", contract_version: 1, params: {} };
    document.layout.switched_off!.gone = { component: "prepare.despike", contract_version: 1, params: {} };
    const written = JSON.parse(writeDesign(document, "Charger health", "")) as PipelineDesignFile;
    expect(written.definition.nodes![1]).toMatchObject({ id: "smooth", component: "features.passthrough", params: {} });
    expect(written.layout!.switched_off).toEqual({ smooth: { component: "prepare.smooth", params: { window: 10 } } });
    expect(JSON.parse(writeDesign(design(), "Charger health", "")).layout).not.toHaveProperty("switched_off");

    const opened = await openDesign(JSON.stringify(written), check);
    expect(opened.document.layout.switched_off).toEqual({ smooth: { component: "prepare.smooth", contract_version: 1, params: { window: 10 } } });
    // A file may leave the version out, and what it says of other steps is not taken.
    const loose = await openDesign(JSON.stringify({ ...written, layout: { ...written.layout, switched_off: {
      smooth: { component: "prepare.smooth", params: { window: 4 } },
      input: { component: "source.other", contract_version: 1, params: {} },
      gone: { component: "prepare.despike", contract_version: 1, params: {} },
    } } }), check);
    expect(loose.document.layout.switched_off).toEqual({ smooth: { component: "prepare.smooth", contract_version: 1, params: { window: 4 } } });
    // What cannot be a step is left out, and the step is then a pass-through step like any other.
    for (const was of ["prepare.smooth", { component: "", params: {} }, { component: "prepare.smooth", params: [] }, null]) {
      const odd = await openDesign(JSON.stringify({ ...written, layout: { ...written.layout, switched_off: { smooth: was } } }), check);
      expect(odd.document.layout).not.toHaveProperty("switched_off");
    }
  });

  it("writes the notes of a design, and opens them", async () => {
    const note = { id: "note_1", x: 288, y: 0, text: "Calm before scoring: the sensor is noisy." };
    const document = { ...design(), layout: { ...design().layout, notes: [note] } };
    const written = JSON.parse(writeDesign(document, "Charger health", "")) as PipelineDesignFile;
    expect(written.layout!.notes).toEqual([note]);
    expect(JSON.parse(writeDesign(design(), "Charger health", "")).layout).not.toHaveProperty("notes");
    expect((await openDesign(JSON.stringify(written), check)).document.layout.notes).toEqual([note]);
    // What is no note is left out; the file is opened all the same.
    const odd = await openDesign(JSON.stringify({ ...written, layout: { ...written.layout, notes: [note, { id: "note_2", text: "No place" }, 7] } }), check);
    expect(odd.document.layout.notes).toEqual([note]);
    expect((await openDesign(JSON.stringify({ ...written, layout: { ...written.layout, notes: "none" } }), check)).document.layout)
      .not.toHaveProperty("notes");
    // A file that places no card is arranged, and its notes come along.
    const loose = await openDesign(file({ layout: { notes: [note] } }), check);
    expect(loose.document.layout.notes).toHaveLength(1);
  });

  it("says why a text is not a design", async () => {
    await expect(openDesign("hello", check)).rejects.toThrow("This file is not a design: it does not hold JSON.");
    await expect(openDesign("[]", check)).rejects.toThrow('A design file says "format": "aberration-design".');
    await expect(openDesign(JSON.stringify({ format: "aberration-system", schema_version: 1 }), check))
      .rejects.toThrow('A design file says "format": "aberration-design".');
    await expect(openDesign(file({ schema_version: 2 }), check)).rejects.toThrow("written in a newer format");
    await expect(openDesign(file({ definition: "steps" }), check)).rejects.toThrow("holds no definition of its steps");
    // The version may be left out, as its default says.
    await expect(openDesign(file({ schema_version: undefined }), check)).resolves.toMatchObject({ name: "Charger health" });
  });

  it("passes on what the server cannot read in the design", async () => {
    const issue = (loc: Array<string | number>, msg: string) => ({ loc: ["body", "definition", ...loc], msg });
    const refuse = (issues: ReturnType<typeof issue>[]) => async () => { throw new ApiRequestError("refused", 422, issues); };
    await expect(openDesign(file(), refuse([issue(["nodes", 0, "kind"], "Input should be 'source'")])))
      .rejects.toThrow("The design in this file cannot be read. definition.nodes.0.kind: Input should be 'source'");
    await expect(openDesign(file(), refuse(["a", "b", "c", "d", "e"].map((name) => issue([name], "Field required")))))
      .rejects.toThrow("definition.a: Field required; definition.b: Field required; definition.c: Field required; and 2 more");
    await expect(openDesign(file(), refuse([]))).rejects.toThrow("The design in this file cannot be read. refused");
    // Any other failure is not about the file.
    await expect(openDesign(file(), async () => { throw new ApiRequestError("Network error. Please check your connection."); }))
      .rejects.toThrow("Network error. Please check your connection.");
  });

  it("refuses a design whose steps share an id", async () => {
    const twin = { ...design().definition, nodes: [...design().definition.nodes, design().definition.nodes[1]!] };
    await expect(openDesign(file({ definition: twin }), check))
      .rejects.toThrow('The design in this file cannot be read. Two of its steps have the id "smooth".');
  });

  it("takes a design that says schema 2 and no other", async () => {
    for (const definition of [{ schema_version: 1, nodes: [] }, { nodes: [] }])
      await expect(openDesign(file({ definition }), check)).rejects.toThrow('A design says "schema_version": 2.');
  });

  it("names a design without a name after its file, and refuses a file that is too large", async () => {
    const { pipelinesApi } = await import("@/features/pipelines/api");
    vi.mocked(pipelinesApi.validate).mockImplementation(check);
    const unnamed = new File([file({ name: "" })], "Pump station.design.json", { type: "application/json" });
    expect((await openDesignFile(unnamed)).name).toBe("Pump station");
    expect((await openDesignFile(new File([file()], "other.json"))).name).toBe("Charger health");
    const large = new File(["x"], "large.json");
    Object.defineProperty(large, "size", { value: MAX_DESIGN_BYTES + 1 });
    await expect(openDesignFile(large)).rejects.toThrow("This file is too large to be a design.");
  });
});
