import { useEffect, useRef, useState } from "react";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type {
  PipelineComponent,
  PipelineDefinition,
  PipelineValidation,
} from "./contracts";
import { arrangeGraph } from "./layout";
import { addComponent, type GraphDocument } from "./model";

type GraphHistory = { undo: GraphDocument[]; redo: GraphDocument[] };
type Options = {
  document: GraphDocument;
  onChange: (document: GraphDocument) => void;
  components: PipelineComponent[];
  readOnly?: boolean;
  historyKey?: string;
  onSelect?: (id: string) => void;
};

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
  const [validation, setValidation] = useState<PipelineValidation>();
  const current = useRef(document);
  const mounted = useRef(false);
  useEffect(() => { current.current = document; }, [document]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const select = (id?: string) => {
    setSelected(id);
    if (id) onSelect?.(id);
  };
  const requestFit = () => setFitRequest((value) => value + 1);
  const resetHistory = () => setHistory({ undo: [], redo: [] });
  const beginMove = () => {
    if (readOnly) return;
    const document = current.current;
    setHistory((previous) => ({
      undo: [...previous.undo.slice(-39), document], redo: [],
    }));
  };
  const commit = (next: GraphDocument, recordHistory = true) => {
    if (readOnly || next === current.current) return;
    const previous = current.current;
    if (recordHistory) {
      setHistory((history) => ({
        undo: [...history.undo.slice(-39), previous], redo: [],
      }));
    }
    if (next.definition !== previous.definition) setValidation(undefined);
    current.current = next;
    onChange(next);
  };
  const undo = () => {
    const next = history.undo[history.undo.length - 1];
    if (readOnly || !next) return;
    const previous = current.current;
    setHistory((history) => ({
      undo: history.undo.slice(0, -1), redo: [...history.redo, previous],
    }));
    commit(next, false);
  };
  const redo = () => {
    const next = history.redo[history.redo.length - 1];
    if (readOnly || !next) return;
    const previous = current.current;
    setHistory((history) => ({
      undo: [...history.undo.slice(-39), previous], redo: history.redo.slice(0, -1),
    }));
    commit(next, false);
  };
  const add = (id: string, position?: { x: number; y: number }) => {
    if (readOnly) return;
    const component = components.find((item) => item.id === id);
    if (!component) return;
    const next = addComponent(current.current, component);
    if (next === current.current) return;
    const added = next.definition.nodes[next.definition.nodes.length - 1]!;
    if (position) next.layout.nodes[added.id] = { ...next.layout.nodes[added.id], ...position };
    commit(next);
    select(added.id);
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
    const result = await request(definition, selected);
    if (!mounted.current || current.current.definition !== definition) return;
    setValidation(result);
    return result;
  };

  return {
    selected, select, fitRequest, requestFit, validation, setValidation,
    commit, beginMove, add, arrange, validate, undo, redo, resetHistory,
    canUndo: history.undo.length > 0, canRedo: history.redo.length > 0,
  };
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
