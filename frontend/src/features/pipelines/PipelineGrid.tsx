import { useId } from "react";
import { Background, BackgroundVariant, useViewport } from "@xyflow/react";
import { GRID_STEP } from "./semantics";

/** Decorative grid follows the same coordinates as node snapping. */
export function PipelineGrid() {
  const id = useId();
  const { zoom } = useViewport();
  // Keep lines at least eight screen pixels apart when viewing large graphs.
  // Coarser lines still fall on the underlying snapping positions.
  const interval = GRID_STEP * 2 ** Math.max(0, Math.ceil(Math.log2(8 / (GRID_STEP * zoom))));
  return <>
    <Background id={`${id}-lines`} className="pl-grid-lines" variant={BackgroundVariant.Lines}
      gap={interval} lineWidth={0.5} color="var(--pl-grid-line)" bgColor="transparent" />
    <Background id={`${id}-markers`} className="pl-grid-markers" variant={BackgroundVariant.Cross}
      gap={interval * 5} size={6 / zoom} lineWidth={1} color="var(--pl-grid-marker)" bgColor="transparent" />
  </>;
}
