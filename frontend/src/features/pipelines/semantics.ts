import type {
  PipelineComponent,
  PipelineEdge,
  PipelineNode,
} from "./contracts";

export type DataKind = NonNullable<PipelineComponent["output_type"]>;

/** Presentation vocabulary; executable types still come from the shared catalog. */
export const dataKinds: Record<DataKind, { label: string; dash?: string }> = {
  features: { label: "Features" },
  scores: { label: "Scores", dash: "8 4" },
  p_values: { label: "P-values", dash: "3 3" },
  decisions: { label: "Decisions", dash: "1 4" },
  evidence: { label: "Evidence", dash: "8 3 2 3" },
};

export const nodeKinds: Record<PipelineNode["kind"], string> = {
  source: "Aligned inputs",
  transform: "Transform",
  merge: "Feature merge",
  detector: "Detector",
  policy: "Alarm policy",
  output: "Evidence output",
};

export const NODE_SIZE = { width: 224, height: 144 };

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
