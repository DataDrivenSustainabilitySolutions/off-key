import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  Controls,
  ControlButton,
  ReactFlow,
  ConnectionLineType,
  SelectionMode,
  applyNodeChanges,
  type OnConnectStartParams,
  type OnConnectEnd,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  ClipboardPaste, Copy, CopyPlus, LocateFixed, Magnet, Pencil, Plus, Power, PowerOff, Save, Scissors, SlidersHorizontal, StickyNote,
  Trash2, Unlink,
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { PipelineBlockCreate } from "@/types/pipelines.generated";
import type { StepChange } from "./comparison";
import type { PipelineBlock, PipelineComponent, PipelineValidation } from "./contracts";
import { addBlockAfter, blockChain, blockChoices, blockedBy, insertBlock, placeBlock, type BlockOutcome } from "./blocks";
import {
  copySteps, duplicateSteps, fragmentSize, heldSteps, holdSteps, pastedNote, pasteSteps, type Pasted, type StepFragment,
} from "./clipboard";
import {
  addAfter, addBlocker, afterBlocker, connectNodes, connectionIssue, disconnectEdge, disconnectNode, duplicateBlocker,
  insertBlocker, insertOnEdge, nodeOptionLabeler, occupiedInput, removeElements, setNodeLabel, stepTitle,
  type GraphDocument, type Link,
} from "./model";
import { PipelineContextMenu } from "./PipelineContextMenu";
import { PipelineDetectorSlot } from "./PipelineDetectorSlot";
import { PipelineShortcuts } from "./PipelineShortcuts";
import { detectorSlot } from "./detectorSlot";
import { stepMenu, type Menu, type MenuItem } from "./contextMenu";
import { PipelineSaveBlock } from "./PipelineSaveBlock";
import { SHORTCUTS } from "./shortcuts";
import { useStepShortcuts } from "./useStepShortcuts";
import { edgeId, NODE_SIZE, nodePosition, SNAP_GRID, switchedOff } from "./semantics";
import { switchOffBlocker, switchSteps } from "./stepSwitch";
import { presentGraph } from "./graphPresentation";
import { PipelineNodeCard } from "./PipelineNodeCard";
import { PipelineNotes, type NoteWriting } from "./PipelineNotes";
import { addNote, moveNote, noteBlocker, notesOf, removeNote, setNoteText } from "./notes";
import { PipelineGrid } from "./PipelineGrid";
import { FIT_ROOM, fitReadableView, revealNode, smallestZoom, VIEW_MARGIN, type CoveredEdges } from "./viewport";
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
  /** The step in focus: the one whose settings show. */
  selected?: string;
  /** Every chosen step, the one in focus among them. They move, copy and are removed together. */
  selection: string[];
  readOnly?: boolean;
  layoutEditable?: boolean;
  states?: Record<string, string>;
  /** How steps differ from the design a service runs now; each such card says so. */
  changes?: Record<string, StepChange>;
  issues?: PipelineValidation["issues"];
  /** Feature columns per component; output ports show how many leave them. */
  features?: PipelineValidation["features"];
  /** The features predate the latest edit and are being checked again. */
  featuresStale?: boolean;
  /** Increment after an explicit arrangement; data refreshes preserve the camera. */
  fitRequest?: number;
  /** Pan just enough to show a newly placed component. */
  reveal?: PlacementRequest;
  /** One step was chosen for its settings, or the choice was let go. */
  onSelect: (id?: string) => void;
  /** Steps were chosen together, with Shift or a box; no settings open for them. */
  onSelectionChange: (ids: string[]) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
  onAdd: (componentId: string, position?: { x: number; y: number }) => void;
  onBeginMove?: () => void;
  /** Edges that the settings cover; fitting and revealing keep cards out from under them. */
  insets?: CoveredEdges;
  /** A card's menu asks for that step's settings. */
  onConfigure?: (id: string) => void;
  /** Offers the place a design without a detector keeps for one; called with the element to open a choice at. */
  onChooseDetector?: (anchor: Element) => void;
  /** A file was dropped on the canvas, such as a design saved as one. */
  onOpenFile?: (file: File) => void;
  /** Saved chains of steps, offered beside the steps wherever a step can be added. */
  blocks?: PipelineBlock[];
  /** Keeps a chain of steps as a block; a card's menu offers it where this is given. */
  onSaveBlock?: (request: PipelineBlockCreate) => Promise<void>;
};

/** What a right-click, long-press or the menu key was aimed at. */
type MenuTarget =
  | { kind: "pane"; position: { x: number; y: number } }
  | { kind: "node"; id: string }
  | { kind: "note"; id: string }
  | { kind: "edge"; link: Link };
const steps = (count: number) => `${count} step${count === 1 ? "" : "s"}`;
/** A touch held this long without moving opens the menu, as a right-click does. */
const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP = 10;

export default function PipelineCanvas({
  document,
  components,
  selected,
  selection,
  readOnly,
  layoutEditable,
  states,
  changes,
  issues,
  features,
  featuresStale,
  fitRequest = 0,
  reveal,
  onSelect,
  onSelectionChange,
  onChange,
  onAdd,
  onBeginMove,
  insets,
  onConfigure,
  onChooseDetector,
  onOpenFile,
  blocks = [],
  onSaveBlock,
}: Props) {
  const { resolvedTheme } = useTheme();
  const [feedback, setFeedback] = useState("");
  // The card whose title is being typed on the card itself.
  const [renaming, setRenaming] = useState<string>();
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
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
  const [measurements, setMeasurements] = useState<Record<string, { width: number; height: number }>>({});
  // Steps inserted on a wire, pasted or duplicated may land beside the view, or push the cards right of it.
  // A menu closed with the graph it was opened on, so keyboard focus moves to the first new card.
  // Their place in the view is known once the cards have been measured.
  const [inserted, setInserted] = useState<string[]>();
  useEffect(() => {
    if (!flow || !inserted?.every((id) => measurements[id])) return;
    const frame = requestAnimationFrame(() => {
      setInserted(undefined);
      const element = surface.current;
      if (!element) return;
      void revealNode(flow, element, inserted, VIEW_MARGIN, covered.current);
      const focused = element.ownerDocument.activeElement;
      if (!focused || focused === element.ownerDocument.body || focused === element)
        element.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(inserted[0]!)}"]`)
          ?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, inserted, measurements]);
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
  const anyChosen = selection.length > 0;
  useEffect(() => {
    if (!anyChosen) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest("input, textarea, select, [role='dialog']")) return;
      release.current();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [anyChosen]);
  // A step chosen with Shift, Ctrl or Cmd held, or with a box, joins the others without opening its settings.
  const additive = useRef(false);
  const boxing = useRef(false);
  const moving = useRef(false);
  const [dragged, setDragged] = useState<{ previous: Map<string, ConnectionRoute>; changed: Set<string> }>();
  const graph = useMemo(
    () => presentGraph(document, components, states, issues, changes),
    [document, components, states, issues, changes],
  );
  const routingBoxes = useMemo(() => document.definition.nodes.map((node, index) => ({
    id: node.id, ...nodePosition(document.layout, node.id, index), ...NODE_SIZE,
  })), [document.definition.nodes, document.layout]);
  // While dragging, reroute only the links of the moving components; drop reroutes everything.
  const routes = useMemo(() => routeConnections(routingBoxes, document.definition.edges, dragged),
    [routingBoxes, document.definition.edges, dragged]);
  const blocked = [...routes.values()].some((route) => route.blocked);
  // A design that can be edited keeps a place for the detector it does not have yet.
  const slot = useMemo(() => (readOnly || !onChooseDetector ? undefined : detectorSlot(document, components)),
    [readOnly, onChooseDetector, document, components]);
  // Zooming out stops at a quarter of full size, where cards can still be told apart, or
  // further out where a large graph needs it to be seen whole.
  const [room, setRoom] = useState<{ width: number; height: number }>();
  useEffect(() => {
    const element = surface.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const { width, height } = element.getBoundingClientRect();
      setRoom((previous) => previous?.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const minZoom = useMemo(() => smallestZoom(routingBoxes, room, insets), [room, routingBoxes, insets]);
  const corner = (id?: string) => routingBoxes.find((box) => box.id === id);
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
      selected: selection.includes(node.id),
      measured: measurements[node.id],
      data: { ...node.data, ...emitted(node.id, node.data.outputType), ...hints(node.id),
        ...(node.id === renaming ? { renaming: true } : {}) },
    }));
  }, [graph.nodes, selection, connecting, document, components, measurements, features, featuresStale, renaming]);
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
    setInserted([result.id]);
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
      if (next !== stepTitle(node)) onChange(setNodeLabel(document, id, next), true);
    },
  };
  const wireActions: WireActions = {
    open: openWire?.definition === document.definition ? openWire.id : undefined,
    setOpen: (id) => setOpenWire(id ? { id, definition: document.definition } : undefined),
    hover,
    menu: (link) => <PipelineToolbox components={components} document={document} link={link}
      onAdd={(componentId) => insert(link, componentId)}
      blocks={blockChoices(blocks, components, (block) => insertBlock(document, link, block, components))}
      onPlace={(placed) => { setOpenWire(undefined); setSelectedEdges([]); applied(placed); }} />,
  };
  // Card centred under the pointer, its corner snapped to the grid as a drop is.
  const placeAt = (clientX: number, clientY: number) => {
    const center = flow?.screenToFlowPosition({ x: clientX, y: clientY }, { snapToGrid: false }) ?? { x: clientX, y: clientY };
    const position = { x: center.x - NODE_SIZE.width / 2, y: center.y - NODE_SIZE.height / 2 };
    return snapToGrid
      ? { x: Math.round(position.x / SNAP_GRID[0]) * SNAP_GRID[0], y: Math.round(position.y / SNAP_GRID[1]) * SNAP_GRID[1] }
      : position;
  };
  // Where the pointer is over the canvas; steps pasted by key land there.
  const pointer = useRef<{ x: number; y: number }>(undefined);
  /** The pointer over the canvas, or the middle of the part of it that nothing covers, on the screen. */
  const aimOnScreen = () => {
    const box = surface.current?.getBoundingClientRect();
    return pointer.current ?? (box ? {
      x: (box.left + box.right - (insets?.right ?? 0)) / 2,
      y: (box.top + (insets?.top ?? 0) + box.bottom - (insets?.bottom ?? 0)) / 2,
    } : { x: 0, y: 0 });
  };
  /** The same place on the graph. */
  const aim = () => {
    const point = aimOnScreen();
    return flow?.screenToFlowPosition(point, { snapToGrid: false }) ?? point;
  };
  /** Show what a paste or a duplicate added: the settings of one step, or the steps as a group. */
  const placed = (verb: string, result: Pasted | undefined) => {
    if (!result) return false;
    setFeedback(pastedNote(verb, result));
    const [first, ...others] = result.ids;
    if (!first) return true;
    onChange(result.document);
    setSelectedEdges([]);
    if (others.length) onSelectionChange(result.ids);
    else onSelect(first);
    setInserted(result.ids);
    return true;
  };
  /** Steps as text for the clipboard, the chosen ones unless others are named; a cut takes them out of the design. */
  const copy = (cut = false, ids = selection) => {
    const fragment = cut && readOnly ? undefined : copySteps(document, ids);
    if (!fragment) return undefined;
    const text = holdSteps(fragment);
    if (cut) {
      onChange(removeElements(document, { nodeIds: ids }));
      onSelect(undefined);
    }
    setFeedback(`${cut ? "Cut" : "Copied"} ${steps(fragment.steps.length)}.`);
    return text;
  };
  /** A menu has no clipboard event to write to, so it asks the browser; Paste in the menu works without it. */
  const copyFromMenu = (cut = false, ids = selection) => {
    const text = copy(cut, ids);
    if (text) void navigator.clipboard?.writeText(text).catch(() => {});
  };
  /** Add steps centred on a place of the graph. */
  const paste = (fragment: StepFragment, centre: { x: number; y: number }) => {
    if (readOnly) return;
    const size = fragmentSize(fragment);
    placed("Pasted", pasteSteps(document, fragment, components, { x: centre.x - size.width / 2, y: centre.y - size.height / 2 }));
  };
  const duplicate = (ids = selection) => !readOnly && placed("Duplicated", duplicateSteps(document, ids, components));
  /** Switch steps off, or on again when none of them is on. Steps that cannot stand aside stay as they are. */
  const switchChosen = (ids = selection) => {
    if (readOnly || !ids.length) return false;
    const turned = switchSteps(document, ids, components);
    if (turned) onChange(turned.document);
    setFeedback(turned ? `Switched ${turned.off ? "off" : "on"} ${steps(turned.ids.length)}.`
      : "Only a step that changes features can be switched off.");
    return true;
  };
  useStepShortcuts(surface, {
    copy: (cut) => copy(cut),
    paste: (fragment) => paste(fragment, aim()),
    duplicate,
    switch: switchChosen,
    selectAll: () => {
      const ids = document.definition.nodes.map((node) => node.id);
      if (ids.length) onSelectionChange(ids);
      return ids.length > 0;
    },
  });
  // The note being written on the canvas: one of the design's, or a new one that joins it once it says something.
  const [noteWriting, setNoteWriting] = useState<NoteWriting>();
  const notes = notesOf(document);
  /** Start a note at the place a card would take there: as wide as the card, its first line where the card's middle would be. */
  const writeNote = (card: { x: number; y: number }) => {
    if (readOnly) return;
    const blocker = noteBlocker(document);
    setFeedback(blocker ?? "");
    const top = card.y + NODE_SIZE.height / 2 - SNAP_GRID[1];
    if (!blocker) setNoteWriting({ at: { x: card.x, y: snapToGrid ? Math.round(top / SNAP_GRID[1]) * SNAP_GRID[1] : top } });
  };
  const keepNote = (text: string | undefined, byKey: boolean) => {
    const writing = noteWriting;
    setNoteWriting(undefined);
    if (!writing) return;
    let id = "id" in writing ? writing.id : undefined;
    if (text !== undefined && "id" in writing) {
      const next = setNoteText(document, writing.id, text);
      if (next !== document) onChange(next);
    } else if (text !== undefined && "at" in writing) {
      const added = addNote(document, writing.at, text);
      if (added) onChange(added.document);
      id = added?.id;
    }
    // The keys stay with the note that was written, or with the canvas when there is none.
    if (byKey) requestAnimationFrame(() => {
      const element = surface.current;
      ((id && element?.querySelector<HTMLElement>(`[data-note="${CSS.escape(id)}"]`)) || element)?.focus({ preventScroll: true });
    });
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
    setInserted([result.id]);
  };
  // The card whose steps are being saved as a block.
  const [savingFrom, setSavingFrom] = useState<string>();
  /** Every block as a menu entry; one that cannot be added here stays listed and says why. */
  const blockItems = (add: (block: PipelineBlock) => BlockOutcome): MenuItem[] =>
    blockChoices(blocks, components, add).map(({ block, detail, outcome }) => ({
      key: `block:${block.id}`, label: block.name, detail, blocked: blockedBy(outcome),
      run: () => { if (!("blocked" in outcome)) applied(outcome); },
    }));
  const anyFits = (items: MenuItem[]) => items.some((item) => !item.blocked);
  const menuFor = (target: MenuTarget): Menu => {
    if (target.kind === "pane") {
      const add = stepMenu("Add a step",
        components.filter((component) => !addBlocker(document.definition, component)),
        (component) => onAdd(component.id, target.position),
        "No step can be added. The design has reached its limit.",
        blockItems((block) => placeBlock(document, block, components, target.position)));
      const held = heldSteps();
      // The card a new step would get stands centred on the place; a note and pasted steps are centred there too.
      return { ...add, items: [...add.items,
        { key: "note", label: "Add a note", icon: StickyNote, keys: SHORTCUTS.note, separated: true,
          blocked: noteBlocker(document), run: () => writeNote(target.position) },
        ...(held ? [{ key: "paste", label: "Paste", detail: steps(held.steps.length), icon: ClipboardPaste, keys: SHORTCUTS.paste,
          run: () => paste(held, { x: target.position.x + NODE_SIZE.width / 2, y: target.position.y + NODE_SIZE.height / 2 }) }] : []),
      ] };
    }
    if (target.kind === "edge") {
      const between = `${nodeName(document, components, target.link.source)} and ${nodeName(document, components, target.link.target)}`;
      const fitting = components.filter((component) => !insertBlocker(document.definition, target.link, component, components));
      const offered = blockItems((block) => insertBlock(document, target.link, block, components));
      return { label: `Connection between ${between}`, items: [
        { key: "insert", label: "Insert here", icon: Plus,
          blocked: fitting.length || anyFits(offered) ? undefined : "No step fits this connection.",
          submenu: stepMenu("Insert a step", fitting,
            (component) => applied(insertOnEdge(document, target.link, component, components)), "No step fits this connection.",
            offered) },
        { key: "delete", label: "Delete connection", icon: Trash2, destructive: true, separated: true,
          run: () => { setSelectedEdges([]); onChange({ ...document, definition: disconnectEdge(document.definition, target.link) }); } },
      ] };
    }
    if (target.kind === "note") return { label: "Note", items: [
      { key: "edit", label: "Edit", icon: Pencil, run: () => setNoteWriting({ id: target.id }) },
      { key: "delete", label: "Delete", icon: Trash2, keys: SHORTCUTS.remove, destructive: true, separated: true,
        run: () => onChange(removeNote(document, target.id)) },
    ] };
    const { id } = target;
    // A step chosen with others answers for all of them.
    if (selection.length > 1 && selection.includes(id)) {
      const turn = switchSteps(document, selection, components);
      return { label: steps(selection.length), items: [
      { key: "duplicate", label: "Duplicate", icon: CopyPlus, keys: SHORTCUTS.duplicate, run: () => { duplicate(); } },
      { key: "copy", label: "Copy", icon: Copy, keys: SHORTCUTS.copy, run: () => copyFromMenu() },
      { key: "cut", label: "Cut", icon: Scissors, keys: SHORTCUTS.cut, run: () => copyFromMenu(true) },
      { key: "switch", label: turn?.off === false ? "Switch on" : "Switch off", icon: turn?.off === false ? Power : PowerOff,
        detail: turn && turn.ids.length < selection.length ? steps(turn.ids.length) : undefined, keys: SHORTCUTS.switch,
        blocked: turn ? undefined : "None of these steps changes features.", run: () => { switchChosen(); } },
      { key: "delete", label: "Delete", icon: Trash2, keys: SHORTCUTS.remove, destructive: true, separated: true,
        run: () => { onChange(removeElements(document, { nodeIds: selection })); onSelect(undefined); } },
      ] };
    }
    const connected = document.definition.edges.some((edge) => edge.source === id || edge.target === id);
    const after = components.filter((component) => !afterBlocker(document, id, component, components));
    const node = document.definition.nodes.find((item) => item.id === id);
    const off = !!switchedOff(document.layout, node);
    const blocksAfter = blockItems((block) => addBlockAfter(document, id, block, components));
    return { label: nodeName(document, components, id), items: [
      { key: "rename", label: "Rename", icon: Pencil, keys: SHORTCUTS.rename, run: () => setRenaming(id) },
      { key: "configure", label: "Configure", icon: SlidersHorizontal, run: () => (onConfigure ?? onSelect)(id) },
      { key: "after", label: "Add after", icon: Plus, separated: true,
        blocked: node?.kind === "output" ? "Evidence output is the last step."
          : after.length || anyFits(blocksAfter) ? undefined : "No step takes this step's output.",
        submenu: stepMenu("Add after", after, (component) => applied(addAfter(document, id, component, components)),
          "No step takes this step's output.", blocksAfter) },
      { key: "duplicate", label: "Duplicate", icon: CopyPlus, keys: SHORTCUTS.duplicate,
        blocked: duplicateBlocker(document.definition, id, components), run: () => { duplicate([id]); } },
      { key: "copy", label: "Copy", icon: Copy, keys: SHORTCUTS.copy, run: () => copyFromMenu(false, [id]) },
      // Listed for the steps it is for; elsewhere it would only say that it cannot be done.
      ...(node?.kind === "transform" ? [{ key: "switch", label: off ? "Switch on" : "Switch off", icon: off ? Power : PowerOff,
        keys: SHORTCUTS.switch, blocked: off ? undefined : switchOffBlocker(document, id, components),
        run: () => { switchChosen([id]); } }] : []),
      ...(onSaveBlock ? [{ key: "block", label: "Save as block", icon: Save,
        blocked: blockChain(document.definition, id).length ? undefined : "A block holds steps between the input and a detector.",
        run: () => setSavingFrom(id) }] : []),
      { key: "disconnect", label: "Disconnect", icon: Unlink, blocked: connected ? undefined : "This step has no connections.",
        run: () => onChange(disconnectNode(document, id)) },
      { key: "delete", label: "Delete", icon: Trash2, keys: SHORTCUTS.remove, destructive: true, separated: true,
        run: () => { onChange(removeElements(document, { nodeIds: [id] })); onSelect(undefined); } },
    ] };
  };
  // Touch has no right button: holding still on the canvas opens the same menu.
  const press = useRef<{ timer?: number; x: number; y: number; target: Element; fired: boolean }>(undefined);
  const targetAt = (element: Element | null, clientX: number, clientY: number): MenuTarget | undefined => {
    const node = element?.closest(".react-flow__node")?.getAttribute("data-id");
    if (node) return { kind: "node", id: node };
    const note = element?.closest("[data-note]")?.getAttribute("data-note");
    if (note) return { kind: "note", id: note };
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
    const file = event.dataTransfer.files[0];
    if (file) return onOpenFile?.(file);
    onAdd(event.dataTransfer.getData("application/off-key-component"), placeAt(event.clientX, event.clientY));
  };
  return (
    <div
      className="pl-canvas-wrap"
      aria-label="Pipeline graph"
      onKeyDown={(event) => {
        // Keys without Ctrl, Cmd or Alt act while the canvas itself is in focus: not in a field
        // on it, and not in a menu or list that it opened, which React reports here as well.
        const origin = event.target as Element;
        if (!event.ctrlKey && !event.metaKey && !event.altKey && !event.defaultPrevented
          && event.currentTarget.contains(origin) && !origin.closest("input, textarea, select, [contenteditable='true']")) {
          const act = event.key === "?" ? () => setShortcutsOpen((open) => !open)
            : event.key === "1" ? () => { void flow?.fitView({ padding: fitPadding(insets, FIT_ROOM, 0.15) }); }
            : event.key === "0" ? () => { if (flow && surface.current) void fitReadableView(flow, surface.current, selected, insets); }
            : event.key === "+" || event.key === "=" ? () => { void flow?.zoomIn(); }
            : event.key === "-" ? () => { void flow?.zoomOut(); }
            : event.key.toLowerCase() === "a" && !event.shiftKey && !readOnly ? () => {
              const point = aimOnScreen();
              openMenu(point.x, point.y, { kind: "pane", position: placeAt(point.x, point.y) });
            }
            : event.key.toLowerCase() === "n" && !event.shiftKey && !readOnly ? () => {
              const point = aimOnScreen();
              writeNote(placeAt(point.x, point.y));
            } : undefined;
          if (act) {
            event.preventDefault();
            act();
            return;
          }
        }
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
      onPointerDownCapture={(event) => { additive.current = event.shiftKey || event.metaKey || event.ctrlKey; }}
      onKeyDownCapture={(event) => { additive.current = event.shiftKey || event.metaKey || event.ctrlKey; }}
      onPointerLeave={() => { pointer.current = undefined; }}
      onPointerMove={(event) => {
        pointer.current = surface.current?.contains(event.target as Node) ? { x: event.clientX, y: event.clientY } : undefined;
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
      onDoubleClick={(event) => {
        // A double-click on empty canvas adds a step there.
        if (readOnly || !(event.target as Element).classList.contains("react-flow__pane")) return;
        openMenu(event.clientX, event.clientY, { kind: "pane", position: placeAt(event.clientX, event.clientY) });
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={drop}
    >
      <div className="pl-flow-surface" ref={surface} tabIndex={-1}>
        <CardActionsContext.Provider value={cardActions}>
        <WireActionsContext.Provider value={wireActions}>
        <ReactFlow<CanvasNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={setFlow}
          colorMode={resolvedTheme}
          minZoom={minZoom}
          maxZoom={2}
          // A double-click on empty canvas adds a step; the wheel, the buttons and the keys zoom.
          zoomOnDoubleClick={false}
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
          onNodeClick={(event, node) => {
            // A plain click chooses this step alone and opens its settings.
            if (!(event.shiftKey || event.metaKey || event.ctrlKey)) onSelect(node.id);
          }}
          onSelectionStart={() => { boxing.current = true; }}
          onSelectionEnd={() => { boxing.current = false; }}
          onPaneClick={() => {
            onSelect(undefined);
            setSelectedEdges([]);
            // Empty canvas cannot hold focus itself; the canvas takes it, so that its keys work after a click.
            surface.current?.focus({ preventScroll: true });
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
            const choices = changes.filter((change) => change.type === "select");
            if (choices.length) {
              const next = new Set(selection);
              for (const change of choices) {
                if (change.selected) next.add(change.id);
                else next.delete(change.id);
              }
              const ids = [...next];
              // One step chosen by itself shows its settings; steps gathered one by one or with a box do not.
              if (ids.length === 1 && choices.some((change) => change.selected) && !additive.current && !boxing.current)
                onSelect(ids[0]);
              else if (ids.length !== selection.length || ids.some((id, index) => id !== selection[index]))
                onSelectionChange(ids);
            }
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
          // Shift draws a box around steps; a click with Shift, Ctrl or Cmd adds a step or takes it out.
          selectionKeyCode="Shift"
          // A step is taken as soon as the box touches it.
          selectionMode={SelectionMode.Partial}
          multiSelectionKeyCode={["Shift", "Meta", "Control"]}
          ariaLabelConfig={{
            "controls.fitView.ariaLabel": "Fit entire graph",
            "node.a11yDescription.default":
              "Press Enter to select a step, or Shift+Enter to select it with others. Use the inspector to edit parameters and connections.",
          }}
        >
          <PipelineGrid />
          {(notes.length > 0 || noteWriting) && <PipelineNotes notes={notes} writing={noteWriting} editable={!readOnly}
            movable={layoutEditable || !readOnly} snapToGrid={snapToGrid}
            onWrite={(id) => setNoteWriting({ id })} onKeep={keepNote}
            onMoveStart={() => onBeginMove?.()} onMove={(id, to) => onChange(moveNote(document, id, to), false)}
            onRemove={(id) => { onChange(removeNote(document, id)); surface.current?.focus({ preventScroll: true }); }}
            onMenu={(event, id) => contextMenuAt(event, { kind: "note", id })} />}
          {slot && onChooseDetector && <PipelineDetectorSlot slot={slot} after={corner(slot.after)} before={corner(slot.before)}
            onChoose={onChooseDetector} />}
          <Controls showInteractive={false} orientation="horizontal" fitViewOptions={{ padding: fitPadding(insets, FIT_ROOM, 0.15) }}>
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
              disabled={!selection.length || !flow}
              onClick={() => {
                // One step at its readable size; several as large as shows them all.
                void flow?.fitView({
                  nodes: selection.map((id) => ({ id })),
                  minZoom: selection.length > 1 ? undefined : 1,
                  maxZoom: 1,
                  padding: fitPadding(insets, 0, selection.length > 1 ? 0.15 : 0.5),
                });
              }}
            >
              <LocateFixed size={16} />
            </ControlButton>
            <PipelineShortcuts open={shortcutsOpen} onOpenChange={setShortcutsOpen} readOnly={readOnly} />
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
      {/* The rings on the cards show a group; this says it to those who cannot see them. */}
      <span className="ex-sr-only" aria-live="polite">{selection.length > 1 ? `${steps(selection.length)} chosen` : ""}</span>
      {onSaveBlock && savingFrom && blockChain(document.definition, savingFrom).length > 0
        && <PipelineSaveBlock document={document} components={components} from={savingFrom} onSave={onSaveBlock}
          onClose={() => setSavingFrom(undefined)} />}
      {(feedback || blocked) && (
        <p className="pl-canvas-feedback" role="status">
          {feedback || "Space components apart to show blocked connections."}
        </p>
      )}
    </div>
  );
}
