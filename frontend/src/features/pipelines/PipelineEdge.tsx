import { useContext, useRef } from "react";
import * as Popover from "@radix-ui/react-popover";
import { BaseEdge, EdgeLabelRenderer, type Edge, type EdgeProps } from "@xyflow/react";
import { Plus, X } from "lucide-react";
import type { DataKind } from "./semantics";
import { WireActionsContext } from "./wireActions";

/** Where a wire offers to insert a step, and what the offer is called. */
type WireInsert = {
  x: number;
  y: number;
  kind?: DataKind;
  /** Both ends, for the button's name, e.g. "Input and Detector". */
  between: string;
};

export type RoutedEdge = Edge<{
  path: string;
  blocked: boolean;
  /** Present where at least one step fits between the two ends. */
  insert?: WireInsert;
  /** Pointed at, focused or selected: the wire stands out and offers its "+". */
  active?: boolean;
}, "pipeline">;

export function PipelineEdge({ id, source, target, data, style, markerEnd, interactionWidth }: EdgeProps<RoutedEdge>) {
  const actions = useContext(WireActionsContext);
  const menu = useRef<HTMLDivElement>(null);
  if (!data) return null;
  const { insert } = data;
  const open = !!actions && actions.open === id;
  const emphasis = data.active || open ? { strokeWidth: 3 } : undefined;
  return <>
    <g data-routing-status={data.blocked ? "blocked" : "routed"}>
      {data.blocked && <title>Space these components apart to show their connection.</title>}
      <BaseEdge id={id} path={data.path} markerEnd={markerEnd} interactionWidth={interactionWidth}
        style={data.blocked ? { ...style, strokeDasharray: "3 4" } : { ...style, ...emphasis }} />
    </g>
    {insert && actions && <EdgeLabelRenderer>
      <div className={`pl-wire-insert pl-data--${insert.kind ?? "unknown"} nodrag nopan${data.active || open ? " is-active" : ""}`}
        style={{ transform: `translate(-50%, -50%) translate(${insert.x}px, ${insert.y}px)` }}
        onPointerEnter={() => actions.hover(id)} onPointerLeave={() => actions.hover()}>
        <Popover.Root open={open} onOpenChange={(next) => actions.setOpen(next ? id : undefined)}>
          <Popover.Trigger aria-label={`Insert a step between ${insert.between}`} title="Insert a step"
            onFocus={() => actions.hover(id)} onBlur={() => actions.hover()}>
            <Plus size={14} strokeWidth={2.4} aria-hidden="true" />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content ref={menu} className="pl-library pl-component-menu" side="bottom" sideOffset={10}
              collisionPadding={12} aria-label="Insert a step" onOpenAutoFocus={(event) => {
                // Typing narrows the steps at once; Close stays one Shift+Tab away.
                const search = menu.current?.querySelector<HTMLInputElement>("input[type='search']");
                if (!search) return;
                event.preventDefault();
                search.focus();
              }}>
              <div className="pl-component-menu-heading"><h3>Insert a step</h3>
                <Popover.Close aria-label="Close steps"><X size={16} aria-hidden="true" /></Popover.Close>
              </div>
              {actions.menu({ source, target })}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
    </EdgeLabelRenderer>}
  </>;
}
