import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Check, LayoutGrid, Redo2, Save, Undo2 } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import { rememberNavigation } from "@/lib/navigation-draft";
import { MonitoringTargetPicker } from "../monitoring/MonitoringTargetPicker";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import { sourceHref } from "../catalogue/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import { normalizeDefinition, normalizeLayout, type PipelineCatalog } from "./contracts";
import type { GraphDocument } from "./model";
import { isDraftDirty } from "./editorSession";
import { useCreationSession, type CreationDraft } from "./creationSession";
import { pipelinesApi } from "./api";
import { useGraphMetadata } from "./useGraphMetadata";
import { useGraphEditor, useUnsavedChanges } from "./useGraphEditor";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineTemplateMenu } from "./PipelineTemplateMenu";
import { PipelineWorkbench, type InspectorPanel } from "./PipelineWorkbench";

function startingDocument(catalog: PipelineCatalog, id?: string, target?: MonitoringTarget, reading?: string): GraphDocument {
  const template = catalog.templates.find((item) => item.id === id) ?? catalog.templates[0];
  if (!template) return { definition: normalizeDefinition({}), layout: normalizeLayout() };
  const readings = target?.inputs.filter((input) => input.binding.policy.mode !== "off"
    && (!reading || !target.inputs.some((item) => item.stream.id === reading) || input.stream.id === reading)) ?? [];
  return {
    definition: {
      ...template.definition,
      input_slots: readings.length ? readings.map((input, index) => ({
        id: index === 0 ? (template.definition.input_slots[0]?.id ?? "input_1") : `input_${index + 1}`,
        label: input.stream.label, unit: input.stream.unit ?? null,
      })) : template.definition.input_slots,
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
  const [inspectorPanel, setInspectorPanel] = useState<InspectorPanel>(null);
  const canAuthor = canEdit && catalog.authoring_enabled;
  const graph = useGraphEditor({
    document: draft.document, components: catalog.components, readOnly: !canAuthor,
    historyKey: `${creationKey}:history`,
    onChange: (document) => setDraft((previous) => ({ ...previous, document,
      startingId: previous.document.definition === document.definition ? previous.startingId : undefined })),
    onSelect: () => setInspectorPanel("component"),
  });
  const { selected, select, fitRequest, validation, commit, add, resetHistory } = graph;
  const metadata = useGraphMetadata(undefined, draft.document.definition, canAuthor, selected);
  const target = targets.find((item) => item.id === draft.targetId);
  const busy = saving || loadingTemplate;
  const message = error || (saveState.status === "error" ? saveState.message : "");
  useUnsavedChanges(isDraftDirty(draft, baseline));

  useEffect(() => {
    if (session.getSnapshot().save.status !== "saved") return;
    const completed = session.takeSaved(initial());
    if (!completed) return;
    rememberNavigation(`pipeline:${userId}:${completed.session.base.id}`, completed.session);
    resetHistory();
    onCreated(completed.session.base.id, completed.targetId);
  }, [initial, onCreated, resetHistory, saveState, session, userId]);

  const load = (document: GraphDocument, name: string, description: string, version: string) => {
    commit(document);
    setDraft((previous) => ({ ...previous, name: previous.name || `${name.slice(0, 113)} (copy)`, description }));
    select(undefined);
    graph.requestFit();
    toast.success(`Loaded ${name} · ${version}. You are editing a separate design.`, { id: "pipeline-create-feedback" });
  };
  const save = () => {
    if (!canAuthor || saving) return;
    if (!draft.name.trim()) { setError("Enter a service name."); setInspectorPanel("service"); return; }
    setError("");
    void session.save();
  };
  const validate = async () => {
    if (validating) return;
    setValidating(true);
    setError("");
    try {
      await graph.validate((definition, selected) => pipelinesApi.validate(undefined, definition, undefined, selected));
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

  return <section className="pl-editor" aria-label="Monitoring workbench">
    <button type="button" className="mn-back" disabled={busy} onClick={onBack}><ArrowLeft size={14} />Monitoring</button>
    <div className="pl-header"><div><h2>Create monitoring service</h2>
    </div><div className="pl-actions">
      {canAuthor && <>
        <PipelineTemplateMenu catalog={catalog} disabled={saving} onLoading={setLoadingTemplate} onManage={onManage}
          onLoad={load} onBuiltIn={(id) => {
            const template = catalog.templates.find((item) => item.id === id)!;
            commit(startingDocument(catalog, id, target, initialReading));
            setDraft((previous) => ({ ...previous, startingId: id }));
            select(undefined); graph.requestFit();
            toast.success(`Loaded ${template.name}.`, { id: "pipeline-create-feedback" });
          }} />
        <button type="button" disabled={busy || validating} onClick={() => void validate()}><Check size={15} />Validate</button>
        <button type="button" className="mn-primary" disabled={busy || validating} onClick={() => void save()}><Save size={15} />Save draft</button>
      </>}
    </div></div>
    {!canAuthor ? <p className="pl-warning" role="status">{canEdit ? "Design authoring is disabled for this deployment."
      : "An administrator can create monitoring services."}</p> : <>
      {message && <p className="pl-error" role="alert">{message}</p>}
      <PipelineWorkbench catalog={catalog} document={draft.document} validation={metadata ?? validation}
        inspectorPanel={inspectorPanel} onInspectorPanelChange={setInspectorPanel}
        selected={selected} fitRequest={fitRequest} onSelect={select} onChange={commit} onAdd={add}
        onBeginMove={graph.beginMove}
        actions={<>
          <button type="button" disabled={!graph.canUndo} aria-label="Undo graph change" title="Undo" onClick={graph.undo}><Undo2 size={15} /></button>
          <button type="button" disabled={!graph.canRedo} aria-label="Redo graph change" title="Redo" onClick={graph.redo}><Redo2 size={15} /></button>
          <button type="button" disabled={arranging} onClick={() => void arrange()}><LayoutGrid size={15} />Arrange</button>
        </>}
        settings={<>
          <label className="pl-field"><span>Service name</span><input maxLength={120} placeholder="e.g. Machine health"
            value={draft.name} onChange={(event) => setDraft((previous) => ({ ...previous, name: event.target.value }))} /></label>
          <div className="pl-field"><span>Inputs</span><MonitoringTargetPicker targets={targets} value={draft.targetId} disabled={busy}
            onChange={(targetId) => {
              if (draft.startingId) {
                const next = startingDocument(catalog, draft.startingId, targets.find((item) => item.id === targetId), initialReading);
                commit({ ...draft.document, definition: { ...draft.document.definition, input_slots: next.definition.input_slots } });
                setDraft((previous) => ({ ...previous, targetId, startingId: draft.startingId }));
              } else setDraft((previous) => ({ ...previous, targetId }));
            }} /></div>
          {target && <p className="pl-help"><Link to={sourceHref(target.inputs.map((input) => input.stream.id), catalogueDocument,
            `${location.pathname}${location.search}`)}>Configure readings in Sources</Link></p>}
          <PipelineDesignSettings document={draft.document} readOnly={false} onChange={commit} />
        </>} />
      {validation && <section className="pl-validation" aria-label="Graph validation">
        <h3>{validation.valid ? "Valid processing graph" : "Validation errors"}</h3>
        {validation.issues_truncated && <p>Additional validation messages were omitted. Resolve the listed issues, then validate again.</p>}
        <ul>{validation.issues.map((issue, index) => <li key={index}>
          <button type="button" onClick={() => issue.node_id && select(issue.node_id)}>{issue.message}</button>
        </li>)}</ul>
      </section>}
    </>}
  </section>;
}
