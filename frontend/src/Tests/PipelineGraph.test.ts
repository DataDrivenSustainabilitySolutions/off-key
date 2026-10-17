import { describe, expect, it } from "vitest";
import {
  addComponent,
  connectNodes,
  executableChanges,
  moveMergeInput,
  removeNode,
} from "@/features/pipelines/model";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineComponent,
} from "@/features/pipelines/contracts";

const definition = () =>
  normalizeDefinition({
    strategy: "adaptive_stream",
    input_slots: [{ id: "temperature", label: "Temperature" }],
    nodes: [
      { id: "source", kind: "source", component: "source.aligned" },
      { id: "scale", kind: "transform", component: "adaptive.standard_scaler" },
      { id: "raw", kind: "transform", component: "features.passthrough" },
      { id: "merge", kind: "merge", component: "features.merge" },
      { id: "model", kind: "detector", component: "detector:aberrant_knn" },
    ],
    edges: [
      { source: "source", target: "scale" },
      { source: "source", target: "raw" },
      { source: "scale", target: "merge", order: 0 },
      { source: "raw", target: "merge", order: 3 },
      { source: "merge", target: "model" },
    ],
  });

const components: PipelineComponent[] = definition().nodes.map((node) => ({
  id: node.component,
  kind: node.kind,
  label: node.component,
  description: "",
  strategies: ["adaptive_stream"],
  fields: [],
  input_type: node.kind === "source" ? null : "features",
  output_type: node.kind === "detector" ? "scores" : "features",
}));

describe("visual pipeline documents", () => {
  it("permits branching, prevents cycles and leaves occupied single inputs unchanged", () => {
    const graph = definition();
    expect(
      connectNodes(graph, "source", "merge", components)
        .edges.filter((edge) => edge.target === "merge")
        .map((edge) => edge.order),
    ).toEqual([0, 1, 2]);
    expect(connectNodes(graph, "model", "scale", components)).toBe(graph);
    expect(connectNodes(graph, "model", "merge", components)).toBe(graph);
    expect(connectNodes(graph, "source", "scale", components)).toBe(graph);
    expect(connectNodes(graph, "raw", "source", components)).toBe(graph);
  });

  it("reorders merge inputs semantically while presentation never changes a definition", () => {
    const graph = definition();
    const reordered = moveMergeInput(graph, "merge", 1, -1);
    expect(reordered.edges.filter((edge) => edge.target === "merge")).toEqual([
      { source: "raw", target: "merge", order: 0 },
      { source: "scale", target: "merge", order: 1 },
    ]);
    const first = {
      definition: graph,
      layout: normalizeLayout({
        nodes: { merge: { x: 1, y: 2, label: "All selected values" } },
      }),
    };
    const moved = {
      ...first,
      layout: normalizeLayout({
        nodes: { merge: { x: 500, y: 100, label: "Combined features" } },
      }),
    };
    expect(executableChanges(first.definition, moved.definition)).toEqual([]);
    expect(executableChanges(graph, reordered)).toEqual([
      "Feature connections or merge order changed",
    ]);
  });

  it("removes all incident connections and its layout when a component is removed", () => {
    const document = removeNode(
      {
        definition: definition(),
        layout: normalizeLayout({
          nodes: { scale: { x: 10, y: 10 }, source: { x: 0, y: 0 } },
        }),
      },
      "scale",
    );
    expect(document.definition.nodes.some((node) => node.id === "scale")).toBe(
      false,
    );
    expect(
      document.definition.edges.some(
        (edge) => edge.source === "scale" || edge.target === "scale",
      ),
    ).toBe(false);
    expect(document.layout.nodes).toEqual({ source: { x: 0, y: 0 } });
  });

  it("adds stable unique IDs and typed descriptor defaults without interpreting arbitrary schemas", () => {
    const component: PipelineComponent = {
      id: "adaptive.standard_scaler",
      kind: "transform",
      label: "Scale",
      description: "",
      strategies: ["adaptive_stream"],
      fields: [
        {
          name: "with_std",
          label: "Standard deviation",
          type: "boolean",
          default: true,
        },
      ],
    };
    const first = addComponent(
      { definition: definition(), layout: normalizeLayout() },
      component,
    );
    const second = addComponent(first, component);
    expect(second.definition.nodes.slice(-2).map((node) => node.id)).toEqual([
      "adaptive_standard_scaler_1",
      "adaptive_standard_scaler_2",
    ]);
    expect(
      second.definition.nodes[second.definition.nodes.length - 1]?.params,
    ).toEqual({ with_std: true });
  });

  it("includes semantic output renaming and learning settings in activation review", () => {
    const before = definition();
    const after = {
      ...before,
      nodes: before.nodes.map((node) =>
        node.id === "raw"
          ? {
              ...node,
              component: "features.rename",
              params: { mapping: { temperature: "temperature_raw" } },
            }
          : node,
      ),
      settings: { ...before.settings, training_window_size: 900 },
    };
    expect(executableChanges(before, after)).toEqual([
      "Updated features.rename (raw)",
      "Learning or calibration settings changed",
    ]);
  });

  it("applies authoring limits to dropped components as well as toolbox buttons", () => {
    const component: PipelineComponent = {
      id: "features.passthrough",
      kind: "transform",
      label: "Raw",
      description: "",
      strategies: ["adaptive_stream"],
      fields: [],
    };
    const full = {
      definition: {
        ...definition(),
        nodes: Array.from({ length: 64 }, (_item, index) => ({
          id: `node_${index}`,
          kind: "transform" as const,
          component: component.id,
          params: {},
        })),
      },
      layout: normalizeLayout(),
    };
    expect(addComponent(full, component)).toBe(full);
    const normal = { definition: definition(), layout: normalizeLayout() };
    expect(addComponent(normal, { ...component, kind: "detector" })).toBe(
      normal,
    );
    expect(
      addComponent(normal, { ...component, strategies: ["static_baseline"] }),
    ).toBe(normal);
  });

  it("excludes display labels and ordering of serialized connections from processing changes", () => {
    const before = definition();
    const after = {
      ...before,
      input_slots: before.input_slots.map((slot) => ({
        ...slot,
        label: "Updated display label",
      })),
      edges: [...before.edges].reverse(),
      nodes: [...before.nodes]
        .reverse()
        .map((node) => ({ ...node, label: "Cosmetic title" })),
    };
    expect(executableChanges(before, after)).toEqual([]);
  });
});
