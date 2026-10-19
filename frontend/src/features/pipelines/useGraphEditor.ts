import { useEffect, useRef, useState } from "react";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type {
  PipelineComponent,
  PipelineDefinition,
  PipelineValidation,
} from "./contracts";
import { arrangeGraph } from "./layout";
import { addComponent, insertAfter, type GraphDocument } from "./model";

type GraphHistory = { undo: GraphDocument[]; redo: GraphDocument[] };
type Options = {
  document: GraphDocument;
  onChange: (document: GraphDocument) => void;
  components: PipelineComponent[];
  readOnly?: boolean;
  historyKey?: string;
  onSelect?: (id: string) => void;
};

/** History entry: `true` records a step, `false` skips it, and a string merges
 * consecutive edits of the same field (typing) into one step. */
export type HistoryMode = boolean | string;
export type PlacementRequest = { id: string; request: number };

/** The same graph operations serve new designs and saved drafts. */
export function useGraphEditor({
  document, onChange, components, readOnly = false, historyKey, onSelect,
}: Options) {
  const [history, setHistory] = useNavigationDraft<GraphHistory>(
    historyKey,
    () => ({ undo: [], redo: [] }),
  );
  const [selected, setSelected] = useState<string>();
  const [fitRequest, setFitRequest] = useState(0);
  const [reveal, setReveal] = useState<PlacementRequest>();
  const [validation, setValidation] = useState<PipelineValidation>();
  const current = useRef(document);
  const latestHistory = useRef(history);
  const lastGroup = useRef<string | undefined>(undefined);
  const mounted = useRef(false);
  useEffect(() => { current.current = document; }, [document]);
  useEffect(() => { latestHistory.current = history; }, [history]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  // A removed component cannot stay selected; Delete would otherwise target nothing visible.
  const present = selected && document.definition.nodes.some((node) => node.id === selected)
    ? selected : undefined;

  const select = (id?: string) => {
    setSelected(id || undefined);
    if (id) onSelect?.(id);
  };
  const requestFit = () => setFitRequest((value) => value + 1);
  const resetHistory = () => {
    lastGroup.current = undefined;
    setHistory({ undo: [], redo: [] });
  };
  const record = (previous: GraphDocument) => {
    const next = {
      undo: [...latestHistory.current.undo.slice(-39), previous], redo: [],
    };
    latestHistory.current = next;
    setHistory(next);
  };
  const beginMove = () => {
    if (readOnly) return;
    lastGroup.current = undefined;
    record(current.current);
  };
  const commit = (next: GraphDocument, mode: HistoryMode = true) => {
    if (readOnly || next === current.current) return;
    const previous = current.current;
    const grouped = typeof mode === "string" && mode === lastGroup.current;
    if (mode !== false && !grouped) record(previous);
    lastGroup.current = typeof mode === "string" ? mode : undefined;
    if (next.definition !== previous.definition) setValidation(undefined);
    current.current = next;
    onChange(next);
  };
  const step = (direction: "undo" | "redo") => {
    const stack = latestHistory.current;
    const from = direction === "undo" ? stack.undo : stack.redo;
    const next = from[from.length - 1];
    if (readOnly || !next) return;
    const previous = current.current;
    const updated = direction === "undo"
      ? { undo: stack.undo.slice(0, -1), redo: [...stack.redo, previous] }
      : { undo: [...stack.undo.slice(-39), previous], redo: stack.redo.slice(0, -1) };
    latestHistory.current = updated;
    setHistory(updated);
    lastGroup.current = undefined;
    commit(next, false);
  };
  const undo = () => step("undo");
  const redo = () => step("redo");
  const add = (id: string, position?: { x: number; y: number }) => {
    if (readOnly) return;
    const component = components.find((item) => item.id === id);
    if (!component) return;
    const placed = addComponent(current.current, component, position, present);
    if (placed === current.current) return;
    const added = placed.definition.nodes[placed.definition.nodes.length - 1]!;
    // A palette click continues the flow from the selected component; a drop stays where it landed.
    const next = present && !position
      ? { ...placed, definition: insertAfter(placed.definition, present, added.id, components) }
      : placed;
    commit(next);
    select(added.id);
    setReveal((previous) => ({ id: added.id, request: (previous?.request ?? 0) + 1 }));
  };
  const arrange = async () => {
    if (readOnly) return false;
    const submitted = current.current;
    const layout = await arrangeGraph(submitted.definition, submitted.layout);
    if (!mounted.current || current.current !== submitted) return false;
    commit({ ...submitted, layout });
    requestFit();
    return true;
  };
  const validate = async (
    request: (definition: PipelineDefinition, selected?: string) => Promise<PipelineValidation>,
  ) => {
    const definition = current.current.definition;
    const result = await request(definition, present);
    if (!mounted.current || current.current.definition !== definition) return;
    setValidation(result);
    return result;
  };

  return {
    selected: present, select, fitRequest, requestFit, reveal, validation, setValidation,
    commit, beginMove, add, arrange, validate, undo, redo, resetHistory,
    canUndo: history.undo.length > 0, canRedo: history.redo.length > 0,
  };
}

/** Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z (or Ctrl+Y) outside text fields, which keep native undo. */
export function useUndoShortcuts(enabled: boolean, undo: () => void, redo: () => void) {
  const handlers = useRef({ undo, redo });
  useEffect(() => { handlers.current = { undo, redo }; });
  useEffect(() => {
    if (!enabled) return;
    const keydown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.defaultPrevented) return;
      const target = event.target;
      if (target instanceof Element
        && target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) handlers.current.undo();
      else if ((key === "z" && event.shiftKey) || (key === "y" && !event.metaKey)) handlers.current.redo();
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [enabled]);
}

export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);
}
