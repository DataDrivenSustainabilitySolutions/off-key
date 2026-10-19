import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, LayoutGrid, Redo2, RotateCcw, Save, Undo2 } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import { rememberNavigation } from "@/lib/navigation-draft";
import { MonitoringTargetPicker } from "../monitoring/MonitoringTargetPicker";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import { sourceHref } from "../catalogue/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import { normalizeDefinition, normalizeLayout, type PipelineCatalog, type PipelineDefinition } from "./contracts";
import type { GraphDocument } from "./model";
import { isDraftDirty } from "./editorSession";
import { useCreationSession, type CreationDraft } from "./creationSession";
import { pipelinesApi } from "./api";
import { useGraphMetadata } from "./useGraphMetadata";
import { useGraphEditor, useUnsavedChanges } from "./useGraphEditor";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineTemplateMenu } from "./PipelineTemplateMenu";
import { PipelineWorkbench, type InspectorPanel } from "./PipelineWorkbench";
import { sameSlots, targetSlots } from "./slots";

const strategyHelp: Record<PipelineDefinition["strategy"], string> = {
  adaptive_stream: "Adaptive stream: learns incrementally from live readings.",
  static_baseline: "Static baseline: fits on a baseline window, then freezes preprocessing.",
};

function startingDocument(catalog: PipelineCatalog, id?: string, target?: MonitoringTarget, reading?: string): GraphDocument {
  const template = catalog.templates.find((item) => item.id === id) ?? catalog.templates[0];
  if (!template) return { definition: normalizeDefinition({}), layout: normalizeLayout() };
  return {
    definition: {
      ...template.definition,
      input_slots: targetSlots(target, template.definition.input_slots, reading) ?? template.definition.input_slots,
    },
    layout: template.layout,
  };
}

export function PipelineCreate({
  catalog, canEdit, targets, initialTarget, initialReading, onCreated, onManage, onBack,
}: {
  catalog: PipelineCatalog;
  canEdit: boolean;
  targets: MonitoringTarget[];
  initialTarget?: string;
  initialReading?: string;
  onCreated: (id: string, targetId?: string) => void;
  onManage: () => void;
  onBack: () => void;
}) {
  const { userId } = useAuth();
  const { document: catalogueDocument } = useCatalogue();
  const location = useLocation();
  const startingId = catalog.templates.find((item) => item.definition.strategy === "adaptive_stream")?.id ?? catalog.templates[0]?.id;
  const initial = useCallback((): CreationDraft => ({
    name: "", description: "", targetId: initialTarget, startingId,
    document: startingDocument(catalog, startingId, targets.find((item) => item.id === initialTarget), initialReading),
  }), [catalog, initialReading, initialTarget, startingId, targets]);
  const creationKey = `pipeline-create:${userId}:${initialTarget ?? ""}:${initialReading ?? ""}`;
  const { draft, baseline, save: saveState, session } = useCreationSession(creationKey, initial);
  const setDraft = session.setDraft;
  const saving = saveState.status === "saving" || saveState.status === "saved";
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const [nameError, setNameError] = useState("");
  const [focusName, setFocusName] = useState(0);
  const [issuesRequest, setIssuesRequest] = useState(0);
  const nameInput = useRef<HTMLInputElement>(null);
  const [inspectorPanel, setInspectorPanel] = useState<InspectorPanel>(null);
  const canAuthor = canEdit && catalog.authoring_enabled;
  const graph = useGraphEditor({
    document: draft.document, components: catalog.components, readOnly: !canAuthor,
    historyKey: `${creationKey}:history`,
    onChange: (document) => setDraft((previous) => ({ ...previous, document })),
    onSelect: () => setInspectorPanel("component"),
  });
  const { selected, select, fitRequest, validation, commit, add, resetHistory } = graph;
  const metadata = useGraphMetadata(undefined, draft.document.definition, canAuthor, selected);
  const target = targets.find((item) => item.id === draft.targetId);
  const busy = saving || loadingTemplate;
  const dirty = isDraftDirty(draft, baseline);
  const message = error || (saveState.status === "error" ? saveState.message : "");
  const matchingSlots = targetSlots(target, draft.document.definition.input_slots, initialReading);
  const slotsMismatch = !!matchingSlots && !sameSlots(matchingSlots, draft.document.definition.input_slots);
  useUnsavedChanges(dirty);

  useEffect(() => {
    if (session.getSnapshot().save.status !== "saved") return;
    const completed = session.takeSaved(initial());
    if (!completed) return;
    rememberNavigation(`pipeline:${userId}:${completed.session.base.id}`, completed.session);
    resetHistory();
    onCreated(completed.session.base.id, completed.targetId);
  }, [initial, onCreated, resetHistory, saveState, session, userId]);
  // Runs after the workbench focuses its panel heading, so the field wins.
  useEffect(() => { if (focusName) nameInput.current?.focus(); }, [focusName]);

  const undoable = (text: string) => toast.success((item) => <span className="pl-toast">
    {text}
    <button type="button" onClick={() => { graph.undo(); toast.dismiss(item.id); }}>Undo</button>
  </span>, { id: "pipeline-create-feedback", duration: 6000 });
  const matchSlots = (slots: PipelineDefinition["input_slots"]) => commit({
    ...draft.document, definition: { ...draft.document.definition, input_slots: slots },
  });
  const load = (document: GraphDocument, name: string, description: string, version: string) => {
    commit(document);
    setDraft((previous) => ({ ...previous, startingId: undefined,
      name: previous.name || `${name.slice(0, 113)} (copy)`, description }));
    select(undefined);
    graph.requestFit();
    undoable(`Loaded ${name} · ${version}. You are editing a separate design.`);
  };
  const save = () => {
    if (!canAuthor || saving) return;
    if (!draft.name.trim()) {
      setNameError("Enter a service name to save the draft.");
      setInspectorPanel("service");
      setFocusName((value) => value + 1);
      return;
    }
    setError("");
    void session.save();
  };
  const validate = async () => {
    if (validating) return;
    setValidating(true);
    setError("");
    try {
      if (await graph.validate((definition, selected) => pipelinesApi.validate(undefined, definition, undefined, selected)))
        setIssuesRequest((value) => value + 1);
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setValidating(false); }
  };
  const arrange = async () => {
    setArranging(true); setError("");
    try {
      if (!await graph.arrange()) toast("The graph changed while arranging. Arrange again to use the latest edits.", { id: "pipeline-create-feedback" });
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setArranging(false); }
  };
  const startOver = () => {
    if (!window.confirm("Discard this unsaved design and start again from the default template?")) return;
    session.discard(initial());
    resetHistory();
    select(undefined);
    setNameError("");
    setError("");
    graph.requestFit();
  };

  return <section className="pl-editor" aria-label="Monitoring workbench">
    <button type="button" className="mn-back" disabled={busy} onClick={onBack}><ArrowLeft size={14} />All services</button>
    <div className="pl-header"><div><h2>Create monitoring service</h2>
      <ol className="pl-steps" aria-label="Creation steps">
        <li aria-current="step">Design and save</li>
        <li>Publish a revision</li>
        <li>Start on readings</li>
      </ol>
      <p className="pl-help">{strategyHelp[draft.document.definition.strategy]} Switch strategy with Templates.</p>
    </div><div className="pl-actions">
      {canAuthor && <>
        {dirty && <button type="button" disabled={busy} onClick={startOver}><RotateCcw size={15} />Start over</button>}
        <PipelineTemplateMenu catalog={catalog} disabled={saving} onLoading={setLoadingTemplate} onManage={onManage}
          onLoad={load} onBuiltIn={(id) => {
            const template = catalog.templates.find((item) => item.id === id)!;
            commit(startingDocument(catalog, id, target, initialReading));
            setDraft((previous) => ({ ...previous, startingId: id }));
            select(undefined); graph.requestFit();
            undoable(`Loaded ${template.name}. The previous graph was replaced.`);
          }} />
        <button type="button" disabled={busy || validating} onClick={() => void validate()}><Check size={15} />Validate</button>
        <button type="button" className="mn-primary" disabled={busy || validating} onClick={() => void save()}><Save size={15} />Save draft</button>
      </>}
    </div></div>
    {!canAuthor ? <p className="pl-warning" role="status">{canEdit ? "Design authoring is disabled for this deployment."
      : "An administrator can create monitoring services."}</p> : <>
      {session.restored && dirty && <p className="pl-notice" role="status">Restored your unsaved design from this browser tab.</p>}
      {message && <p className="pl-error" role="alert">{message}</p>}
      <PipelineWorkbench catalog={catalog} document={draft.document} validation={metadata ?? validation}
        inspectorPanel={inspectorPanel} onInspectorPanelChange={setInspectorPanel}
        selected={selected} fitRequest={fitRequest} reveal={graph.reveal} onSelect={select} onChange={commit} onAdd={add}
        onBeginMove={graph.beginMove} onUndo={graph.undo} onRedo={graph.redo} issuesRequest={issuesRequest}
        actions={<>
          <button type="button" disabled={!graph.canUndo} aria-label="Undo graph change" title="Undo (Ctrl+Z)" onClick={graph.undo}><Undo2 size={15} /></button>
          <button type="button" disabled={!graph.canRedo} aria-label="Redo graph change" title="Redo (Ctrl+Shift+Z)" onClick={graph.redo}><Redo2 size={15} /></button>
          <button type="button" disabled={arranging} onClick={() => void arrange()}><LayoutGrid size={15} />Arrange</button>
        </>}
        settings={<>
          <label className="pl-field"><span>Service name</span><input ref={nameInput} maxLength={120} placeholder="e.g. Machine health"
            aria-invalid={!!nameError} aria-describedby={nameError ? "pl-create-name-error" : undefined}
            value={draft.name} onChange={(event) => {
              const name = event.target.value;
              if (name.trim()) setNameError("");
              setDraft((previous) => ({ ...previous, name }));
            }} />
            {nameError && <small className="pl-field-error" id="pl-create-name-error">{nameError}</small>}
          </label>
          <div className="pl-field"><span>Inputs</span><MonitoringTargetPicker targets={targets} value={draft.targetId} disabled={busy}
            onChange={(targetId) => {
              // Choosing readings is an explicit request for matching slots, whatever was edited before.
              const slots = targetSlots(targets.find((item) => item.id === targetId),
                draft.document.definition.input_slots, initialReading);
              if (slots && !sameSlots(slots, draft.document.definition.input_slots)) matchSlots(slots);
              setDraft((previous) => ({ ...previous, targetId }));
            }} /></div>
          {target && slotsMismatch && matchingSlots && <p className="pl-warning" role="status">
            The input slots differ from the readings of {target.label}.{" "}
            <button type="button" onClick={() => matchSlots(matchingSlots)}>Match slots to readings</button>
          </p>}
          {target && <p className="pl-help"><Link to={sourceHref(target.inputs.map((input) => input.stream.id), catalogueDocument,
            `${location.pathname}${location.search}`)}>Configure readings in Sources</Link></p>}
          <PipelineDesignSettings document={draft.document} readOnly={false} onChange={commit} />
        </>} />
    </>}
  </section>;
}
