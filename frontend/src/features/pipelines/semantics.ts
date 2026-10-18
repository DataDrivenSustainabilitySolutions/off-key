import type {
  PipelineComponent,
  PipelineEdge,
  PipelineNode,
  PipelineLayout,
} from "./contracts";

export type DataKind = NonNullable<PipelineComponent["output_type"]>;

/** Presentation vocabulary; executable types still come from the shared catalog. */
export const dataKinds: Record<DataKind, { label: string }> = {
  features: { label: "Features" },
  scores: { label: "Scores" },
  p_values: { label: "P-values" },
  decisions: { label: "Decisions" },
  evidence: { label: "Evidence" },
};

export const nodeKinds: Record<PipelineNode["kind"], string> = {
  source: "Input",
  transform: "Transform",
  merge: "Combine",
  detector: "Detector",
  policy: "Decision policy",
  output: "Evidence output",
};

export const NODE_SIZE = { width: 224, height: 144 };
export const GRID_STEP = 16;
export const SNAP_GRID: [number, number] = [GRID_STEP, GRID_STEP];

export function nodePosition(layout: PipelineLayout, id: string, index: number) {
  const position = layout.nodes[id];
  return position ? { x: position.x, y: position.y } : { x: index * 270, y: 100 };
}

/** V1 permits one connection per node pair; array position is never identity. */
export const edgeId = (edge: Pick<PipelineEdge, "source" | "target">) =>
  JSON.stringify([edge.source, edge.target]);

export function componentFor(
  node: PipelineNode | undefined,
  components: PipelineComponent[],
) {
  return (
    node &&
    components.find(
      (component) =>
        component.id === node.component &&
        component.kind === node.kind &&
        (component.contract_version ?? 1) === (node.contract_version ?? 1),
    )
  );
}

export function inputKind(component: PipelineComponent | undefined) {
  return component
    ? component.input_type === null
      ? null
      : (component.input_type ?? "features")
    : undefined;
}

export function outputKind(
  node: PipelineNode,
  component: PipelineComponent | undefined,
) {
  // Evidence is persisted by the V1 sink; it is not another routable output.
  return component && node.kind !== "output"
    ? (component.output_type ?? "features")
    : undefined;
}

export function sampledState(state: string) {
  const text = state.replace(/_/g, " ");
  const label = text.charAt(0).toUpperCase() + text.slice(1);
  const tone =
    state === "failed"
      ? "failed"
      : state === "waiting"
        ? "waiting"
        : state === "ready"
          ? "ready"
          : "neutral";
  return { label, tone };
}
