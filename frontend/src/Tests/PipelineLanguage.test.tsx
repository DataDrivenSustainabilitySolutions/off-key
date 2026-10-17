import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineComponent,
} from "@/features/pipelines/contracts";
import { connectionIssue, connectNodes } from "@/features/pipelines/model";
import { presentGraph } from "@/features/pipelines/graphPresentation";
import { edgeId } from "@/features/pipelines/semantics";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";

const components: PipelineComponent[] = [
  {
    id: "source.aligned",
    kind: "source",
    label: "Aligned inputs",
    description: "Aligned readings",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: null,
    output_type: "features",
  },
  {
    id: "features.passthrough",
    kind: "transform",
    label: "Pass through",
    description: "Preserve incoming values",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: "features",
    output_type: "features",
  },
  {
    id: "features.merge",
    kind: "merge",
    label: "Merge features",
    description: "Ordered columns",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: "features",
    output_type: "features",
  },
  {
    id: "detector:test",
    kind: "detector",
    label: "Detector",
    description: "Online model",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: "features",
    output_type: "scores",
  },
  {
    id: "policy.test",
    kind: "policy",
    label: "Threshold",
    description: "Alarm threshold",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: "scores",
    output_type: "decisions",
  },
  {
    id: "output.evidence",
    kind: "output",
    label: "Evidence",
    description: "Persist evidence",
    strategies: ["adaptive_stream"],
    fields: [],
    input_type: "decisions",
    output_type: "evidence",
  },
];
const fixture = () => ({
  definition: normalizeDefinition({
    strategy: "adaptive_stream",
    input_slots: [{ id: "x", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "left", kind: "transform", component: "features.passthrough" },
      { id: "right", kind: "transform", component: "features.passthrough" },
      { id: "merge", kind: "merge", component: "features.merge" },
      { id: "model", kind: "detector", component: "detector:test" },
      { id: "policy", kind: "policy", component: "policy.test" },
      { id: "output", kind: "output", component: "output.evidence" },
    ],
    edges: [
      { source: "input", target: "left" },
      { source: "input", target: "right" },
      { source: "left", target: "merge", order: 0 },
      { source: "right", target: "merge", order: 127 },
      { source: "merge", target: "model" },
      { source: "model", target: "policy" },
      { source: "policy", target: "output" },
    ],
  }),
  layout: normalizeLayout({
    nodes: { left: { x: 10, y: 20, label: "Unmodified temperature" } },
  }),
});
afterEach(cleanup);

describe("monitoring graph visual language", () => {
  it("retains operation identity beneath a custom title and keeps validation separate from execution", () => {
    const document = fixture();
    const before = structuredClone(document);
    const graph = presentGraph(document, components, { left: "ready" }, [
      { node_id: "left", code: "configuration", message: "Check selection" },
    ]);
    expect(graph.nodes.find((node) => node.id === "left")?.data).toMatchObject({
      label: "Unmodified temperature",
      operation: "Pass through",
      state: "ready",
      issueCount: 1,
    });
    expect(graph.edges.find((edge) => edge.source === "model")).toMatchObject({
      ariaLabel: expect.stringMatching(/: Scores$/),
      sourceHandle: "output",
      targetHandle: "input",
      markerEnd: expect.any(Object),
    });
    expect(graph.edges.every((edge) => edge.label === undefined)).toBe(true);
    expect(
      graph.nodes.find((node) => node.id === "output")?.data,
    ).toMatchObject({ inputType: "decisions", outputPort: false });
    expect(document).toEqual(before);
  });

  it("keeps connection identity and accessible merge ranks through insertion/deletion of sparse saved orders", () => {
    const document = fixture();
    const graph = presentGraph(document, components);
    const key = edgeId({ source: "right", target: "merge" });
    expect(graph.edges.find((edge) => edge.id === key)?.ariaLabel).toMatch(
      /: Features · input 2$/,
    );
    const changed = {
      ...document,
      definition: {
        ...document.definition,
        edges: document.definition.edges
          .filter((edge) => edge.source !== "left")
          .reverse(),
      },
    };
    expect(
      presentGraph(changed, components).edges.find((edge) => edge.id === key)
        ?.ariaLabel,
    ).toMatch(/: Features · input 1$/);
    expect(edgeId({ source: "a-b", target: "c" })).not.toBe(
      edgeId({ source: "a", target: "b-c" }),
    );
    const connected = connectNodes(
      document.definition,
      "input",
      "merge",
      components,
    );
    expect(
      connected.edges
        .filter((edge) => edge.target === "merge")
        .map((edge) => edge.order),
    ).toEqual([0, 1, 2]);
  });

  it("rejects incompatible data kinds, unknown contracts and cycles before creating a wire", () => {
    const document = fixture();
    expect(
      connectionIssue(document.definition, "model", "merge", components),
    ).toContain("Scores to Features");
    expect(
      connectionIssue(document.definition, "input", "policy", components),
    ).toContain("Features to Scores");
    expect(
      connectionIssue(document.definition, "output", "left", components),
    ).toContain("terminal");
    expect(
      connectionIssue(document.definition, "input", "merge", []),
    ).toContain("metadata");
    const free = {
      ...document.definition,
      edges: document.definition.edges.filter((edge) => edge.target !== "left"),
    };
    expect(connectionIssue(free, "merge", "left", components)).toContain(
      "cycle",
    );
    expect(connectNodes(free, "merge", "left", components)).toBe(free);
    const unavailable = {
      ...document,
      definition: {
        ...document.definition,
        nodes: document.definition.nodes.map((node) =>
          node.id === "left" ? { ...node, contract_version: 2 } : node,
        ),
      },
    };
    const graph = presentGraph(unavailable, components);
    expect(graph.nodes.find((node) => node.id === "left")?.data).toMatchObject({
      available: false,
      inputPort: true,
      outputPort: true,
    });
    expect(graph.edges.find((edge) => edge.source === "left")?.ariaLabel).toMatch(
      /: Unavailable type · input 1$/,
    );
  });

  it("offers the keyboard inspector exactly the compatible upstream choices", () => {
    const document = fixture();
    const definition = {
      ...document.definition,
      edges: document.definition.edges.filter(
        (edge) => edge.target !== "model",
      ),
    };
    render(
      <PipelineInspector
        document={{ ...document, definition }}
        catalog={{
          catalog_id: "catalog",
          authoring_enabled: true,
          components,
          templates: [],
        }}
        selected="model"
        onSelect={() => {}}
        onChange={() => {}}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Connect input from" });
    expect(
      [...select.querySelectorAll("option")].map((option) => option.value),
    ).toEqual(["", "input", "left", "right", "merge"]);
    expect(
      screen.getByText("Only compatible, cycle-free connections are listed."),
    ).toBeTruthy();
  });

  it("preserves the distinction between calibrated P-values and raw scores", () => {
    const document = fixture();
    document.definition.strategy = "static_baseline";
    const staticComponents = components.map((component) => ({
      ...component,
      strategies: ["static_baseline" as const],
      output_type:
        component.kind === "detector"
          ? ("p_values" as const)
          : component.output_type,
      input_type:
        component.kind === "policy"
          ? ("p_values" as const)
          : component.input_type,
    }));
    const graph = presentGraph(document, staticComponents);
    expect(graph.nodes.find((node) => node.id === "model")?.data.outputType).toBe(
      "p_values",
    );
    expect(graph.edges.find((edge) => edge.source === "model")?.ariaLabel).toMatch(
      /: P-values$/,
    );
  });
});
