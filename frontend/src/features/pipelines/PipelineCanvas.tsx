import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  Controls,
  ControlButton,
  ReactFlow,
  ConnectionLineType,
  applyNodeChanges,
  type OnConnectStartParams,
  type OnConnectEnd,
  type ReactFlowInstance,
} from "@xyflow/react";
import { LocateFixed, Magnet } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { PipelineComponent, PipelineValidation } from "./contracts";
import { connectNodes, connectionIssue, type GraphDocument } from "./model";
import { edgeId, NODE_SIZE, nodePosition, SNAP_GRID } from "./semantics";
import { presentGraph } from "./graphPresentation";
import { PipelineNodeCard, type CanvasNode } from "./PipelineNodeCard";
import { PipelineGrid } from "./PipelineGrid";
import { fitReadableView, revealNode } from "./viewport";
import type { HistoryMode, PlacementRequest } from "./useGraphEditor";
import { PipelineEdge } from "./PipelineEdge";
import { routeConnections, type ConnectionRoute } from "./routing";
import "@xyflow/react/dist/style.css";

const nodeTypes = { component: PipelineNodeCard };
const edgeTypes = { pipeline: PipelineEdge };
type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  selected?: string;
  readOnly?: boolean;
  layoutEditable?: boolean;
  states?: Record<string, string>;
  issues?: PipelineValidation["issues"];
  /** Increment after an explicit arrangement; data refreshes preserve the camera. */
  fitRequest?: number;
  /** Pan just enough to show a newly placed component. */
  reveal?: PlacementRequest;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
  onAdd: (componentId: string, position?: { x: number; y: number }) => void;
  onBeginMove?: () => void;
};

export default function PipelineCanvas({
  document,
  components,
  selected,
  readOnly,
  layoutEditable,
  states,
  issues,
  fitRequest = 0,
  reveal,
  onSelect,
  onChange,
  onAdd,
  onBeginMove,
}: Props) {
  const { resolvedTheme } = useTheme();
  const [feedback, setFeedback] = useState("");
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [flow, setFlow] = useState<ReactFlowInstance<CanvasNode>>();
  const [zoom, setZoom] = useState(1);
  const [connecting, setConnecting] = useState<OnConnectStartParams>();
  const surface = useRef<HTMLDivElement>(null);
  const lastFit = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!flow || !surface.current || lastFit.current === fitRequest) return;
    lastFit.current = fitRequest;
    void fitReadableView(flow, surface.current, selected);
  }, [fitRequest, flow, selected]);
  const lastReveal = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!flow || !surface.current || !reveal || lastReveal.current === reveal.request) return;
    lastReveal.current = reveal.request;
    const frame = requestAnimationFrame(() => {
      if (surface.current) void revealNode(flow, surface.current, reveal.id);
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, reveal]);
  // The settings panel narrows the canvas; keep the component being edited in view.
  const selectedRef = useRef(selected);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => {
    const element = surface.current;
    if (!flow || !element || typeof ResizeObserver === "undefined") return;
    let previous = element.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const width = element.getBoundingClientRect().width;
      if (width === previous) return;
      previous = width;
      if (selectedRef.current) void revealNode(flow, element, selectedRef.current);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [flow]);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  // Escape releases the selection so Delete cannot remove a component the user moved away from.
  // An open settings panel or popover consumes the first Escape itself.
  const release = useRef(() => {});
  useEffect(() => {
    release.current = () => {
      onSelect(undefined);
      setSelectedEdges([]);
    };
  });
  useEffect(() => {
    if (!selected) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest("input, textarea, select, [role='dialog']")) return;
      release.current();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [selected]);
  const [measurements, setMeasurements] = useState<Record<string, { width: number; height: number }>>({});
  const moving = useRef(false);
  const [dragged, setDragged] = useState<{ previous: Map<string, ConnectionRoute>; changed: Set<string> }>();
  const graph = useMemo(
    () => presentGraph(document, components, states, issues),
    [document, components, states, issues],
  );
  const routingBoxes = useMemo(() => document.definition.nodes.map((node, index) => ({
    id: node.id, ...nodePosition(document.layout, node.id, index), ...NODE_SIZE,
  })), [document.definition.nodes, document.layout]);
  // While dragging, reroute only the links of the moving components; drop reroutes everything.
  const routes = useMemo(() => routeConnections(routingBoxes, document.definition.edges, dragged),
    [routingBoxes, document.definition.edges, dragged]);
  const blocked = [...routes.values()].some((route) => route.blocked);
  const nodes = useMemo(
    () =>
      graph.nodes.map((node) => ({
        ...node,
        selected: node.id === selected,
        measured: measurements[node.id],
        data: {
          ...node.data,
          inputIssue: connecting?.nodeId && connecting.handleType === "source"
            ? connectionIssue(document.definition, connecting.nodeId, node.id, components) ?? null
            : undefined,
          outputIssue: connecting?.nodeId && connecting.handleType === "target"
            ? connectionIssue(document.definition, node.id, connecting.nodeId, components) ?? null
            : undefined,
        },
      })),
    [graph.nodes, selected, connecting, document.definition, components, measurements],
  );
  const connectingNode = graph.nodes.find((node) => node.id === connecting?.nodeId);
  const connectingType = connecting?.handleType === "source"
    ? connectingNode?.data.outputType : connectingNode?.data.inputType;
  const endConnection: OnConnectEnd = (_event, connection) => {
    setConnecting(undefined);
    if (connection.isValid === false && connection.fromNode && connection.toNode) {
      const [source, target] = connection.fromHandle?.type === "source"
        ? [connection.fromNode.id, connection.toNode.id]
        : [connection.toNode.id, connection.fromNode.id];
      setFeedback(connectionIssue(document.definition, source, target, components) ?? "");
    }
  };
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        type: "pipeline",
        data: routes.get(edge.id),
        selectable: !readOnly,
        selected: selectedEdges.includes(edge.id),
      })),
    [graph.edges, readOnly, selectedEdges, routes],
  );
  const drop = (event: DragEvent) => {
    event.preventDefault();
    if (readOnly || !flow) return;
    // Center the card under the exact pointer, then snap only its corner to the grid.
    const center = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }, { snapToGrid: false });
    const position = { x: center.x - NODE_SIZE.width / 2, y: center.y - NODE_SIZE.height / 2 };
    onAdd(
      event.dataTransfer.getData("application/off-key-component"),
      snapToGrid
        ? { x: Math.round(position.x / SNAP_GRID[0]) * SNAP_GRID[0], y: Math.round(position.y / SNAP_GRID[1]) * SNAP_GRID[1] }
        : position,
    );
  };
  return (
    <div
      className="pl-canvas-wrap"
      aria-label="Pipeline graph"
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={drop}
    >
      <div className="pl-flow-surface" ref={surface}>
        <ReactFlow<CanvasNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={setFlow}
          colorMode={resolvedTheme}
          minZoom={0.01}
          maxZoom={2}
          onMoveEnd={(_event, viewport) => setZoom(viewport.zoom)}
          snapToGrid={snapToGrid}
          snapGrid={SNAP_GRID}
          nodesDraggable={layoutEditable || !readOnly}
          nodesConnectable={!readOnly}
          onConnectStart={(_event, start) => { setFeedback(""); setConnecting(start); }}
          onConnectEnd={endConnection}
          onClickConnectStart={(_event, start) => { setFeedback(""); setConnecting(start); }}
          onClickConnectEnd={endConnection}
          connectionLineStyle={{ stroke: connectingType ? `var(--pl-${connectingType})` : undefined, strokeWidth: 2 }}
          connectionLineType={ConnectionLineType.SmoothStep}
          isValidConnection={(connection) =>
            !readOnly &&
            !connectionIssue(
              document.definition,
              connection.source,
              connection.target,
              components,
            )
          }
          elementsSelectable
          onNodeClick={(_event, node) => onSelect(node.id)}
          onPaneClick={() => {
            onSelect(undefined);
            setSelectedEdges([]);
          }}
          onNodeDragStart={(_event, _node, moved) => {
            moving.current = true;
            setDragged({ previous: routes, changed: new Set(moved.map((node) => node.id)) });
            onBeginMove?.();
          }}
          onNodeDragStop={() => {
            moving.current = false;
            setDragged(undefined);
          }}
          onNodesChange={(changes) => {
            // Retain renderer measurements when domain data or connection hints change.
            // Dropping them also clears React Flow's handle bounds until a resize.
            if (changes.some((change) => change.type === "dimensions" && change.dimensions)) {
              setMeasurements((previous) => {
                const next: typeof previous = {};
                for (const node of nodes) if (previous[node.id]) next[node.id] = previous[node.id]!;
                for (const change of changes) {
                  if (change.type === "dimensions" && change.dimensions) next[change.id] = change.dimensions;
                }
                return next;
              });
            }
            const selection = changes.find(
              (change) => change.type === "select" && change.selected,
            );
            if (selection?.type === "select") onSelect(selection.id);
            const positions = changes.filter(
              (change) => change.type === "position",
            );
            if ((readOnly && !layoutEditable) || !positions.length) return;
            const next = applyNodeChanges<CanvasNode>(positions, nodes);
            onChange(
              {
                ...document,
                layout: {
                  ...document.layout,
                  nodes: Object.fromEntries(
                    next.map((node) => [
                      node.id,
                      { ...document.layout.nodes[node.id], ...node.position },
                    ]),
                  ),
                },
              },
              !moving.current,
            );
          }}
          onEdgesChange={(changes) =>
            setSelectedEdges((previous) => {
              const next = new Set(previous);
              for (const change of changes)
                if (change.type === "select") {
                  if (change.selected) next.add(change.id);
                  else next.delete(change.id);
                }
              return [...next];
            })
          }
          onConnect={(connection) => {
            const issue = connectionIssue(
              document.definition,
              connection.source,
              connection.target,
              components,
            );
            if (issue) {
              setFeedback(issue);
              return;
            }
            const definition = connectNodes(
              document.definition,
              connection.source,
              connection.target,
              components,
            );
            setFeedback("");
            onChange({ ...document, definition });
          }}
          onBeforeDelete={async ({
            nodes: removedNodes,
            edges: removedEdges,
          }) => {
            if (readOnly) return false;
            const ids = new Set(removedNodes.map((node) => node.id));
            const edgeIds = new Set(removedEdges.map((edge) => edge.id));
            onChange({
              definition: {
                ...document.definition,
                nodes: document.definition.nodes.filter(
                  (node) => !ids.has(node.id),
                ),
                edges: document.definition.edges.filter(
                  (edge) =>
                    !ids.has(edge.source) &&
                    !ids.has(edge.target) &&
                    !edgeIds.has(edgeId(edge)),
                ),
              },
              layout: {
                ...document.layout,
                nodes: Object.fromEntries(
                  Object.entries(document.layout.nodes).filter(
                    ([id]) => !ids.has(id),
                  ),
                ),
              },
            });
            setSelectedEdges([]);
            return false;
          }}
          deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
          ariaLabelConfig={{
            "controls.fitView.ariaLabel": "Fit entire graph",
            "node.a11yDescription.default":
              "Press Enter to select a component. Use the inspector to edit parameters and connections.",
          }}
        >
          <PipelineGrid />
          <Controls showInteractive={false} orientation="horizontal" fitViewOptions={{ padding: 0.15 }}>
            <ControlButton
              className="pl-canvas-scale"
              aria-label="Readable size"
              title="Return to readable size"
              onClick={() => { if (flow && surface.current) void fitReadableView(flow, surface.current, selected); }}
            >
              {Math.round(zoom * 100)}%
            </ControlButton>
            {(layoutEditable || !readOnly) && <ControlButton
              aria-label="Snap to grid"
              aria-pressed={snapToGrid}
              title={`Snap to grid: ${snapToGrid ? "on" : "off"}`}
              onClick={() => setSnapToGrid((value) => !value)}
            >
              <Magnet size={16} />
            </ControlButton>}
            <ControlButton
              aria-label="Locate selected component"
              title="Locate selected component"
              disabled={!selected || !flow}
              onClick={() => {
                if (selected)
                  void flow?.fitView({
                    nodes: [{ id: selected }],
                    minZoom: 1,
                    maxZoom: 1,
                    padding: 0.5,
                  });
              }}
            >
              <LocateFixed size={16} />
            </ControlButton>
          </Controls>
        </ReactFlow>
      </div>
      {(feedback || blocked) && (
        <p className="pl-canvas-feedback" role="status">
          {feedback || "Space components apart to show blocked connections."}
        </p>
      )}
    </div>
  );
}
