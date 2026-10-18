import { BaseEdge, type Edge, type EdgeProps } from "@xyflow/react";

export type RoutedEdge = Edge<{ path: string; blocked: boolean }, "pipeline">;

export function PipelineEdge({ id, data, style, markerEnd, interactionWidth }: EdgeProps<RoutedEdge>) {
  if (!data) return null;
  return <g data-routing-status={data.blocked ? "blocked" : "routed"}>
    {data.blocked && <title>Space these components apart to show their connection.</title>}
    <BaseEdge id={id} path={data.path} markerEnd={markerEnd} interactionWidth={interactionWidth}
      style={data.blocked ? { ...style, strokeDasharray: "3 4" } : style} />
  </g>;
}
