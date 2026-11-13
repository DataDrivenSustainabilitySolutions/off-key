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
  forecasts: { label: "Forecasts" },
  // A fixed split gives p-values; a method that adapts gives scores against its boundary.
  p_values: { label: "Calibrated scores" },
  decisions: { label: "Decisions" },
  evidence: { label: "Evidence" },
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

/** The step that stands in for one that is switched off: features leave it as they came. */
export const PASS_THROUGH = "features.passthrough";

/** What a step was before it was switched off; undefined for a step that is on. */
export const switchedOff = (layout: PipelineLayout | undefined, node: PipelineNode | undefined) =>
  node?.component === PASS_THROUGH ? layout?.switched_off?.[node.id] : undefined;

/** The component a card stands for: its step's own, or the one the step had before it was switched off. */
export function shownComponent(node: PipelineNode | undefined, components: PipelineComponent[], layout?: PipelineLayout) {
  const was = switchedOff(layout, node);
  return componentFor(was && node ? { ...node, component: was.component, contract_version: was.contract_version } : node, components);
}

export function inputKind(component: PipelineComponent | undefined) {
  return component
    ? component.input_type === null
      ? null
      : (component.input_type ?? "features")
    : undefined;
}

/** Whether a step takes what a connection carries. A calibration step reads a
 * forecaster's forecasts as it reads a detector's scores. */
export function takes(component: PipelineComponent | undefined, carried: DataKind | undefined) {
  const input = inputKind(component);
  return !!carried && (input === carried
    || (component?.kind === "calibration" && carried === "forecasts"));
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
