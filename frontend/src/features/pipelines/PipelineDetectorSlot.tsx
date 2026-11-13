import { useId } from "react";
import { ViewportPortal } from "@xyflow/react";
import type { DetectorSlot } from "./detectorSlot";
import { NODE_SIZE } from "./semantics";

type Corner = { x: number; y: number };

/** From one card's right edge to the next card's left edge: straight in a row, a soft curve otherwise. */
function wire(from: Corner, to: Corner) {
  const start = { x: from.x + NODE_SIZE.width, y: from.y + NODE_SIZE.height / 2 };
  const end = { x: to.x, y: to.y + NODE_SIZE.height / 2 };
  const bend = Math.max(24, (end.x - start.x) / 2);
  return `M ${start.x} ${start.y} C ${start.x + bend} ${start.y}, ${end.x - bend} ${end.y}, ${end.x} ${end.y}`;
}

/**
 * The place a design without a detector keeps for one. It is drawn on the canvas and is
 * no step of the design: choosing a detector here adds the step and its connections.
 */
export function PipelineDetectorSlot({ slot, after, before, onChoose }: {
  slot: DetectorSlot;
  /** Where the cards on either side of the slot sit. */
  after?: Corner;
  before?: Corner;
  onChoose: (anchor: Element) => void;
}) {
  const hint = useId();
  return <ViewportPortal>
    <svg className="pl-detector-slot-wires" aria-hidden="true">
      {after && <path d={wire(after, slot.position)} />}
      {before && <path d={wire(slot.position, before)} />}
    </svg>
    <button type="button" className="pl-detector-slot nodrag nopan" aria-haspopup="menu"
      aria-label="Choose a detector" aria-describedby={hint}
      style={{ transform: `translate(${slot.position.x}px, ${slot.position.y}px)`, ...NODE_SIZE }}
      onClick={(event) => onChoose(event.currentTarget)}>
      <span className="pl-detector-slot-kind">Detector</span>
      <span className="pl-detector-slot-title">
        <strong>Choose a detector</strong>
        <small id={hint}>It scores how unusual each observation is.</small>
      </span>
    </button>
  </ViewportPortal>;
}
