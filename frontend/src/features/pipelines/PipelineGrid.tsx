import { useId } from "react";
import { Background, BackgroundVariant, useViewport } from "@xyflow/react";
import { GRID_STEP } from "./semantics";

/** Smallest distance between dots on screen, so a zoomed-out canvas stays calm. */
const MIN_DOT_SPACING = 20;

/** Decorative dots fall on the same coordinates as node snapping. */
export function PipelineGrid() {
  const id = useId();
  const { zoom } = useViewport();
  // Coarser spacing at small zooms still lands on the underlying snapping positions.
  const interval = GRID_STEP * 2 ** Math.max(0, Math.ceil(Math.log2(MIN_DOT_SPACING / (GRID_STEP * zoom))));
  return <Background id={`${id}-dots`} className="pl-grid-dots" variant={BackgroundVariant.Dots}
    gap={interval} size={1.4} color="var(--pl-grid-dot)" bgColor="transparent" />;
}
