import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
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
import { Copy, LocateFixed, Magnet, Pencil, Plus, SlidersHorizontal, Trash2, Unlink } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { PipelineComponent, PipelineValidation } from "./contracts";
import {
  addAfter, addBlocker, afterBlocker, connectNodes, connectionIssue, disconnectEdge, disconnectNode, duplicateBlocker,
  duplicateNode, insertBlocker, insertOnEdge, nodeOptionLabeler, occupiedInput, removeElements, setNodeLabel,
  type GraphDocument, type Link,
} from "./model";
import { PipelineContextMenu } from "./PipelineContextMenu";
import { stepMenu, type Menu } from "./contextMenu";
import { edgeId, NODE_SIZE, nodePosition, SNAP_GRID } from "./semantics";
import { presentGraph } from "./graphPresentation";
import { PipelineNodeCard } from "./PipelineNodeCard";
import { PipelineGrid } from "./PipelineGrid";
import { fitReadableView, revealNode, VIEW_MARGIN, type CoveredEdges } from "./viewport";
import type { CanvasNode, HistoryMode, PlacementRequest } from "./types";
import { PipelineEdge, type RoutedEdge } from "./PipelineEdge";
import { PipelineToolbox } from "./PipelineToolbox";
import { routeConnections, routeHandles, type ConnectionRoute } from "./routing";
import { WireActionsContext, type WireActions } from "./wireActions";
import { CardActionsContext, type CardActions } from "./cardActions";
import "@xyflow/react/dist/style.css";

const nodeTypes = { component: PipelineNodeCard };

/** The connection that linking source to target would replace, if any. */
function displaced(definition: GraphDocument["definition"], source: string, target: string) {
  const occupied = occupiedInput(definition, target);
  return occupied && occupied.source !== source ? occupied : undefined;
}

const nodeName = (document: GraphDocument, components: PipelineComponent[], id: string) =>
  nodeOptionLabeler(document, components)(document.definition.nodes.find((node) => node.id === id));
const edgeTypes = { pipeline: PipelineEdge };

/** Fit padding that keeps the graph clear of floating controls, plus a margin of room. */
function fitPadding(covered: CoveredEdges | undefined, room: number, fallback: number) {
  if (!covered?.top && !covered?.right && !covered?.bottom) return fallback;
  const side = (edge = 0) => `${edge + room}px` as const;
  return { top: side(covered.top), right: side(covered.right), bottom: side(covered.bottom), left: side() };
}
type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  selected?: string;
  readOnly?: boolean;
  layoutEditable?: boolean;
  states?: Record<string, string>;
  issues?: PipelineValidation["issues"];
  /** Feature columns per component; output ports show how many leave them. */
  features?: PipelineValidation["features"];
  /** The features predate the latest edit and are being checked again. */
  featuresStale?: boolean;
  /** Increment after an explicit arrangement; data refreshes preserve the camera. */
  fitRequest?: number;
  /** Pan just enough to show a newly placed component. */
  reveal?: PlacementRequest;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
  onAdd: (componentId: string, position?: { x: number; y: number }) => void;
  onBeginMove?: () => void;
  /** Edges that floating controls cover; fitting and revealing keep cards out from under them. */
  insets?: CoveredEdges;
  /** A card's menu asks for that step's settings. */
  onConfigure?: (id: string) => void;
};

/** What a right-click, long-press or the menu key was aimed at. */
type MenuTarget =
  | { kind: "pane"; position: { x: number; y: number } }
  | { kind: "node"; id: string }
  | { kind: "edge"; link: Link };
/** A touch held this long without moving opens the menu, as a right-click does. */
const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP = 10;

export default function PipelineCanvas({
  document,
  components,
  selected,
  readOnly,
  layoutEditable,
  states,
  issues,
  features,
  featuresStale,
  fitRequest = 0,
  reveal,
  onSelect,
  onChange,
  onAdd,
  onBeginMove,
  insets,
  onConfigure,
}: Props) {
  const { resolvedTheme } = useTheme();
  const [feedback, setFeedback] = useState("");
  // The card whose title is being typed on the card itself.
  const [renaming, setRenaming] = useState<string>();
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [flow, setFlow] = useState<ReactFlowInstance<CanvasNode>>();
  const [zoom, setZoom] = useState(1);
  const [connecting, setConnecting] = useState<OnConnectStartParams>();
  // A step menu belongs to the graph it was opened on; any edit closes it.
  const [openWire, setOpenWire] = useState<{ id: string; definition: GraphDocument["definition"] }>();
  const [hoveredWire, setHoveredWire] = useState<string>();
  const hoverTimer = useRef<number | undefined>(undefined);
  // Leaving a wire for its label, or the label for the wire, keeps the offer to insert.
  const hover = useCallback((id?: string) => {
    window.clearTimeout(hoverTimer.current);
    if (id) setHoveredWire(id);
    else hoverTimer.current = window.setTimeout(() => setHoveredWire(undefined), 120);
  }, []);
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);
  const surface = useRef<HTMLDivElement>(null);
  const covered = useRef(insets);
  useEffect(() => { covered.current = insets; }, [insets]);
  const lastFit = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!flow || !surface.current || lastFit.current === fitRequest) return;
    lastFit.current = fitRequest;
    void fitReadableView(flow, surface.current, selected, covered.current);
  }, [fitRequest, flow, selected]);
  const lastReveal = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!flow || !surface.current || !reveal || lastReveal.current === reveal.request) return;
    lastReveal.current = reveal.request;
    const frame = requestAnimationFrame(() => {
      if (surface.current) void revealNode(flow, surface.current, reveal.id, VIEW_MARGIN, covered.current);
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, reveal]);
  // A step inserted on a wire may land beside the view, or push the cards right of it.
  // Its menu closed with the wire it was opened on, so keyboard focus moves to the new card.
  const [inserted, setInserted] = useState<string>();
  useEffect(() => {
    if (!flow || !inserted) return;
    const frame = requestAnimationFrame(() => {
      setInserted(undefined);
      const element = surface.current;
      if (!element) return;
      void revealNode(flow, element, inserted, VIEW_MARGIN, covered.current);
      const focused = element.ownerDocument.activeElement;
      if (!focused || focused === element.ownerDocument.body)
        element.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(inserted)}"]`)
          ?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, inserted]);
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
      if (selectedRef.current) void revealNode(flow, element, selectedRef.current, VIEW_MARGIN, covered.current);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [flow]);
  // A floating settings panel covers the canvas instead of narrowing it.
  useEffect(() => {
    if (flow && surface.current && selectedRef.current && (insets?.right || insets?.bottom))
      void revealNode(flow, surface.current, selectedRef.current, VIEW_MARGIN, insets);
  }, [flow, insets]);
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
  const handles = useMemo(() => routeHandles(routes), [routes]);
  // A wire offers "+" only where some step fits; the menu lists exactly those.
  const insertable = useMemo(() => new Set(readOnly ? [] : document.definition.edges
    .filter((edge) => components.some((component) => !insertBlocker(document.definition, edge, component, components)))
    .map(edgeId)), [readOnly, document.definition, components]);
  const nodes = useMemo(() => {
    // While a wire is drawn, every dot says whether it can take it; an occupied
    // input takes it by replacing its current connection.
    const hints = (id: string) => {
      if (!connecting?.nodeId) return {};
      const [source, target] = connecting.handleType === "source" ? [connecting.nodeId, id] : [id, connecting.nodeId];
      const issue = connectionIssue(document.definition, source, target, components, { replace: true }) ?? null;
      if (connecting.handleType === "target") return { outputIssue: issue };
      const replaced = issue === null ? displaced(document.definition, source, target) : undefined;
      return { inputIssue: issue, inputReplaces: replaced && nodeName(document, components, replaced.source) };
    };
    // An output port of features says how many columns leave it, as the compiler reports them.
    const slotLabels = new Map(document.definition.input_slots.map((slot) => [slot.id, slot.label || slot.id]));
    const emitted = (id: string, kind?: string) => {
      const columns = kind === "features" ? features?.[id] : undefined;
      return columns ? {
        outputCount: columns.length,
        outputFeatures: columns.map((column) => slotLabels.get(column.name) ?? column.name),
        outputStale: featuresStale,
      } : {};
    };
    return graph.nodes.map((node) => ({
      ...node,
      selected: node.id === selected,
      measured: measurements[node.id],
      data: { ...node.data, ...emitted(node.id, node.data.outputType), ...hints(node.id),
        ...(node.id === renaming ? { renaming: true } : {}) },
    }));
  }, [graph.nodes, selected, connecting, document, components, measurements, features, featuresStale, renaming]);
  const connectingNode = graph.nodes.find((node) => node.id === connecting?.nodeId);
  const connectingType = connecting?.handleType === "source"
    ? connectingNode?.data.outputType : connectingNode?.data.inputType;
  const endConnection: OnConnectEnd = (_event, connection) => {
    setConnecting(undefined);
    if (connection.isValid === false && connection.fromNode && connection.toNode) {
      const [source, target] = connection.fromHandle?.type === "source"
        ? [connection.fromNode.id, connection.toNode.id]
        : [connection.toNode.id, connection.fromNode.id];
      setFeedback(connectionIssue(document.definition, source, target, components, { replace: true }) ?? "");
    }
  };
  const edges = useMemo(
    () =>
      graph.edges.map((edge): RoutedEdge => {
        const route = routes.get(edge.id);
        const position = handles.get(edge.id);
        const source = graph.nodes.find((node) => node.id === edge.source);
        const target = graph.nodes.find((node) => node.id === edge.target);
        return {
          ...edge,
          type: "pipeline",
          data: route && {
            ...route,
            insert: position && insertable.has(edge.id) ? {
              ...position,
              kind: source?.data.outputType,
              between: `${source?.ariaLabel ?? edge.source} and ${target?.ariaLabel ?? edge.target}`,
            } : undefined,
            // While a new wire is drawn, existing wires do not offer to insert.
            active: !readOnly && !connecting && (hoveredWire === edge.id || selectedEdges.includes(edge.id)),
          },
          selectable: !readOnly,
          selected: selectedEdges.includes(edge.id),
        };
      }),
    [graph, readOnly, selectedEdges, routes, handles, insertable, hoveredWire, connecting],
  );
  const insert = (link: Link, componentId: string) => {
    setOpenWire(undefined);
    const component = components.find((item) => item.id === componentId);
    const result = component && insertOnEdge(document, link, component, components);
    if (!result) return;
    setFeedback("");
    setSelectedEdges([]);
    onChange(result.document);
    onSelect(result.id);
    setInserted(result.id);
  };
  const cardElement = (id: string) =>
    surface.current?.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(id)}"]`);
  const cardActions: CardActions = {
    finishRename: (id, title) => {
      setRenaming(undefined);
      // Back on the card, so the keyboard carries on where the rename started.
      requestAnimationFrame(() => cardElement(id)?.focus({ preventScroll: true }));
      if (title === undefined) return;
      const node = document.definition.nodes.find((item) => item.id === id);
      const operation = node && components.find((item) => item.id === node.component)?.label;
      // A title equal to the step's own name, or none, shows that name again.
      const next = title.trim() === operation ? "" : title.trim();
      if (next !== (document.layout.nodes[id]?.label ?? "")) onChange(setNodeLabel(document, id, next), true);
    },
  };
  const wireActions: WireActions = {
    open: openWire?.definition === document.definition ? openWire.id : undefined,
    setOpen: (id) => setOpenWire(id ? { id, definition: document.definition } : undefined),
    hover,
    menu: (link) => <PipelineToolbox components={components} document={document} link={link}
      onAdd={(componentId) => insert(link, componentId)} />,
  };
  // Card centred under the pointer, its corner snapped to the grid as a drop is.
  const placeAt = (clientX: number, clientY: number) => {
    const center = flow?.screenToFlowPosition({ x: clientX, y: clientY }, { snapToGrid: false }) ?? { x: clientX, y: clientY };
    const position = { x: center.x - NODE_SIZE.width / 2, y: center.y - NODE_SIZE.height / 2 };
    return snapToGrid
      ? { x: Math.round(position.x / SNAP_GRID[0]) * SNAP_GRID[0], y: Math.round(position.y / SNAP_GRID[1]) * SNAP_GRID[1] }
      : position;
  };
  // A menu belongs to the graph it was opened on; any edit closes it, as a wire's menu does.
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; target: MenuTarget;
    definition: GraphDocument["definition"]; returnFocus: Element | null }>();
  const shownMenu = contextMenu?.definition === document.definition ? contextMenu : undefined;
  const openMenu = (x: number, y: number, target: MenuTarget) => {
    if (readOnly || !flow) return;
    setOpenWire(undefined);
    setContextMenu({ x, y, target, definition: document.definition, returnFocus: window.document.activeElement });
  };
  const applied = (result: { document: GraphDocument; id: string } | undefined) => {
    if (!result) return;
    setFeedback("");
    onChange(result.document);
    onSelect(result.id);
    setInserted(result.id);
  };
  const menuFor = (target: MenuTarget): Menu => {
    if (target.kind === "pane") return stepMenu("Add a step",
      components.filter((component) => !addBlocker(document.definition, component)),
      (component) => onAdd(component.id, target.position),
      "No step can be added. The design has reached its limit.");
    if (target.kind === "edge") {
      const between = `${nodeName(document, components, target.link.source)} and ${nodeName(document, components, target.link.target)}`;
      const fitting = components.filter((component) => !insertBlocker(document.definition, target.link, component, components));
      return { label: `Connection between ${between}`, items: [
        { key: "insert", label: "Insert here", icon: Plus, blocked: fitting.length ? undefined : "No step fits this connection.",
          submenu: stepMenu("Insert a step", fitting,
            (component) => applied(insertOnEdge(document, target.link, component, components)), "No step fits this connection.") },
        { key: "delete", label: "Delete connection", icon: Trash2, destructive: true, separated: true,
          run: () => { setSelectedEdges([]); onChange({ ...document, definition: disconnectEdge(document.definition, target.link) }); } },
      ] };
    }
    const { id } = target;
    const connected = document.definition.edges.some((edge) => edge.source === id || edge.target === id);
    const after = components.filter((component) => !afterBlocker(document, id, component, components));
    const node = document.definition.nodes.find((item) => item.id === id);
    return { label: nodeName(document, components, id), items: [
      { key: "rename", label: "Rename", icon: Pencil, run: () => setRenaming(id) },
      { key: "configure", label: "Configure", icon: SlidersHorizontal, run: () => (onConfigure ?? onSelect)(id) },
      { key: "after", label: "Add after", icon: Plus, separated: true,
        blocked: node?.kind === "output" ? "Evidence output is the last step."
          : after.length ? undefined : "No step takes this step's output.",
        submenu: stepMenu("Add after", after, (component) => applied(addAfter(document, id, component, components)),
          "No step takes this step's output.") },
      { key: "duplicate", label: "Duplicate", icon: Copy, blocked: duplicateBlocker(document.definition, id, components),
        run: () => applied(duplicateNode(document, id, components)) },
      { key: "disconnect", label: "Disconnect", icon: Unlink, blocked: connected ? undefined : "This step has no connections.",
        run: () => onChange(disconnectNode(document, id)) },
      { key: "delete", label: "Delete", icon: Trash2, destructive: true, separated: true,
        run: () => { onChange(removeElements(document, { nodeIds: [id] })); onSelect(undefined); } },
    ] };
  };
  // Touch has no right button: holding still on the canvas opens the same menu.
  const press = useRef<{ timer?: number; x: number; y: number; target: Element; fired: boolean }>(undefined);
  const targetAt = (element: Element | null, clientX: number, clientY: number): MenuTarget | undefined => {
    const node = element?.closest(".react-flow__node")?.getAttribute("data-id");
    if (node) return { kind: "node", id: node };
    const edge = element?.closest(".react-flow__edge")?.getAttribute("data-id");
    const link = edge ? document.definition.edges.find((item) => edgeId(item) === edge) : undefined;
    if (link) return { kind: "edge", link: { source: link.source, target: link.target } };
    if (element?.closest(".react-flow__pane")) return { kind: "pane", position: placeAt(clientX, clientY) };
  };
  const contextMenuAt = (event: { clientX: number; clientY: number; preventDefault: () => void }, target: MenuTarget) => {
    if (readOnly) return;
    event.preventDefault();
    // A touch device may report its own long-press after ours; one gesture opens one menu.
    if (press.current) {
      window.clearTimeout(press.current.timer);
      if (press.current.fired) return;
      press.current.fired = true;
    }
    openMenu(event.clientX, event.clientY, target);
  };
  const endPress = () => { if (press.current) window.clearTimeout(press.current.timer); };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    if (readOnly || !flow) return;
    onAdd(event.dataTransfer.getData("application/off-key-component"), placeAt(event.clientX, event.clientY));
  };
  return (
    <div
      className="pl-canvas-wrap"
      aria-label="Pipeline graph"
      onKeyDown={(event) => {
        // F2 renames a focused card, as it renames a file.
        const card = (event.target as Element).closest?.(".react-flow__node");
        if (!readOnly && event.key === "F2" && card === event.target) {
          const id = card.getAttribute("data-id");
          if (id) { event.preventDefault(); setRenaming(id); }
          return;
        }
        // The menu key, or Shift+F10, opens a focused card's or wire's menu.
        if (readOnly || !(event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey))) return;
        const element = event.target as Element;
        const box = element.getBoundingClientRect();
        const target = targetAt(element, box.left + box.width / 2, box.top + box.height / 2);
        if (!target || target.kind === "pane") return;
        event.preventDefault();
        openMenu(box.left + Math.min(box.width / 2, 48), box.top + Math.min(box.height / 2, 32), target);
      }}
      onPointerDown={(event) => {
        if (readOnly || event.pointerType !== "touch") return;
        endPress();
        const target = event.target as Element;
        const { clientX: x, clientY: y } = event;
        press.current = { x, y, target, fired: false, timer: window.setTimeout(() => {
          const aimed = targetAt(target, x, y);
          if (!aimed || !press.current || press.current.fired) return;
          press.current.fired = true;
          openMenu(x, y, aimed);
        }, LONG_PRESS_MS) };
      }}
      onPointerMove={(event) => {
        const current = press.current;
        if (current && !current.fired && Math.hypot(event.clientX - current.x, event.clientY - current.y) > LONG_PRESS_SLOP) endPress();
      }}
      onPointerUp={endPress}
      onPointerCancel={endPress}
      onClickCapture={(event) => {
        // Lifting the finger after a long-press does not also select or connect.
        if (press.current?.fired) { event.stopPropagation(); event.preventDefault(); }
        press.current = undefined;
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={drop}
    >
      <div className="pl-flow-surface" ref={surface}>
        <CardActionsContext.Provider value={cardActions}>
        <WireActionsContext.Provider value={wireActions}>
        <ReactFlow<CanvasNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={setFlow}
          colorMode={resolvedTheme}
          minZoom={0.01}
          maxZoom={2}
          onMoveStart={() => { setOpenWire(undefined); setContextMenu(undefined); }}
          onNodeDoubleClick={readOnly ? undefined : (event, node) => {
            // A double-click on the title renames the step in place.
            if ((event.target as Element).closest(".pl-node-title > strong")) setRenaming(node.id);
          }}
          onPaneContextMenu={readOnly ? undefined : (event) => contextMenuAt(event, { kind: "pane", position: placeAt(event.clientX, event.clientY) })}
          onNodeContextMenu={readOnly ? undefined : (event, node) => contextMenuAt(event, { kind: "node", id: node.id })}
          onEdgeContextMenu={readOnly ? undefined : (event, edge) => contextMenuAt(event, { kind: "edge", link: { source: edge.source, target: edge.target } })}
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
              { replace: true },
            )
          }
          elementsSelectable
          onEdgeMouseEnter={(_event, edge) => hover(edge.id)}
          onEdgeMouseLeave={() => hover()}
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
              { replace: true },
            );
            if (issue) {
              setFeedback(issue);
              return;
            }
            // Dropping on an occupied input replaces its connection; undo restores it.
            const replaced = displaced(document.definition, connection.source, connection.target);
            const definition = connectNodes(
              document.definition,
              connection.source,
              connection.target,
              components,
              { replace: true },
            );
            setFeedback(replaced ? `Replaced the input from ${nodeName(document, components, replaced.source)}.` : "");
            onChange({ ...document, definition });
          }}
          onBeforeDelete={async ({
            nodes: removedNodes,
            edges: removedEdges,
          }) => {
            if (readOnly) return false;
            onChange(removeElements(document, {
              nodeIds: removedNodes.map((node) => node.id),
              edgeIds: removedEdges.map((edge) => edge.id),
            }));
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
          <Controls showInteractive={false} orientation="horizontal" fitViewOptions={{ padding: fitPadding(insets, 48, 0.15) }}>
            <ControlButton
              className="pl-canvas-scale"
              aria-label="Readable size"
              title="Return to readable size"
              onClick={() => { if (flow && surface.current) void fitReadableView(flow, surface.current, selected, insets); }}
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
                    padding: fitPadding(insets, 0, 0.5),
                  });
              }}
            >
              <LocateFixed size={16} />
            </ControlButton>
          </Controls>
        </ReactFlow>
        </WireActionsContext.Provider>
        </CardActionsContext.Provider>
      </div>
      {shownMenu && <PipelineContextMenu x={shownMenu.x} y={shownMenu.y} menu={menuFor(shownMenu.target)}
        onClose={(restore) => {
          setContextMenu(undefined);
          if (restore && shownMenu.returnFocus instanceof HTMLElement) shownMenu.returnFocus.focus({ preventScroll: true });
        }} />}
      {(feedback || blocked) && (
        <p className="pl-canvas-feedback" role="status">
          {feedback || "Space components apart to show blocked connections."}
        </p>
      )}
    </div>
  );
}
