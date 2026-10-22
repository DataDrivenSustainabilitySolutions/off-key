import { useCallback, useEffect, useRef, useState } from "react";
import { Check, LayoutGrid, Play, Redo2, RotateCcw, Undo2 } from "lucide-react";
import { Breadcrumb } from "@/components/Breadcrumb";
import { useConfirm } from "@/hooks/use-confirm";
import { Link, useLocation } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import { MonitoringTargetPicker } from "../monitoring/MonitoringTargetPicker";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import { sourceHref } from "../catalogue/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import { normalizeDefinition, normalizeLayout, type PipelineCatalog, type PipelineServiceView, type PipelineView } from "./contracts";
import type { GraphDocument } from "./model";
import { useCreationSession, type CreationDraft } from "./creationSession";
import { pipelinesApi } from "./api";
import { useGraphMetadata } from "./useGraphMetadata";
import { useGraphEditor, useUnsavedChanges } from "./useGraphEditor";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineTemplateMenu } from "./PipelineTemplateMenu";
import { PipelineSaveTemplate } from "./PipelineSaveTemplate";
import { PipelineWorkbench, type InspectorPanel } from "./PipelineWorkbench";
import { PipelineInputBindings } from "./PipelineInputBindings";
import { PipelineReadingPicker } from "./PipelineReadingPicker";
import { PipelineApplyStatus } from "./PipelineApplyStatus";
import { usePipelineApply } from "./applySession";
import { bindingsReady, suggestBindings } from "./bindings";
import { selectReadings, targetInputs } from "./slots";

export type PipelineSetupProps = {
  catalog: PipelineCatalog; canEdit: boolean; targets: MonitoringTarget[];
  services: ActiveService[]; byStream: Map<string, Set<string>>; collectionReady: boolean;
  initialTarget?: string; initialReading?: string; initialDesign?: PipelineView;
  initialDocument?: GraphDocument; replaceService?: ActiveService; predecessor?: PipelineServiceView;
  revisionId?: string;
  sourceService?: { id: string; replace: boolean };
  activationBlocked?: string; onManage: () => void; onBack: () => void; onStarted: (id: string) => void;
  /** Names where onBack leads, for the breadcrumb. */
  backLabel?: string;
};

function startingSetup(catalog: PipelineCatalog, id?: string, target?: MonitoringTarget, reading?: string) {
  const template = catalog.templates.find((item) => item.id === id) ?? catalog.templates[0];
  const inputs = targetInputs(target, template?.definition.input_slots ?? [], reading);
  return { document: { definition: template ? { ...template.definition,
    input_slots: inputs?.slots ?? template.definition.input_slots } : normalizeDefinition({}), layout: template?.layout ?? normalizeLayout() },
  bindings: inputs?.bindings ?? {} };
}

/** The same setup surface configures a new service, a template or a replacement. */
export function PipelineCreate(props: PipelineSetupProps) {
  const { catalog, targets, initialTarget, initialReading, initialDesign, initialDocument, replaceService, predecessor, onStarted } = props;
  const { userId } = useAuth();
  const { document: catalogueDocument } = useCatalogue();
  const [confirm, confirmation] = useConfirm();
  const location = useLocation();
  const replaceId = props.sourceService?.replace ? props.sourceService.id : replaceService?.id;
  const sourceId = props.sourceService?.id ?? replaceId;
  const startingId = catalog.templates.find((item) => item.definition.strategy === "adaptive_stream")?.id ?? catalog.templates[0]?.id;
  const initial = useCallback((): CreationDraft => {
    const targetId = initialTarget ?? targets.find((target) => target.inputs.some((input) =>
      predecessor?.run?.execution?.bindings.some((binding) => binding.reading_id === input.stream.id)))?.id;
    const target = targets.find((item) => item.id === targetId);
    const starting = startingSetup(catalog, startingId, target, initialReading);
    const document = initialDocument ?? (initialDesign
      ? { definition: initialDesign.draft, layout: initialDesign.layout }
      : starting.document);
    return { name: replaceService?.display_name ?? initialDesign?.name ?? "", description: initialDesign?.description ?? "",
      targetId, startingId: initialDesign || initialDocument ? undefined : startingId, document,
      bindings: initialDesign || initialDocument ? suggestBindings(document.definition.input_slots, target,
        Object.fromEntries((predecessor?.run?.execution?.bindings ?? []).map((binding) => [binding.slot_id, binding.reading_id]))) : starting.bindings };
  }, [catalog, initialDesign, initialDocument, initialReading, initialTarget, predecessor, replaceService, startingId, targets]);
  const creationKey = `pipeline-setup:${userId}:${initialDesign?.id ?? "new"}:${props.revisionId ?? "draft"}:${sourceId ?? initialTarget ?? ""}:${replaceId ? "replace" : "new"}:${initialReading ?? ""}`;
  const { draft, template, save: saveState, session } = useCreationSession(creationKey, initial,
    !replaceId && !props.revisionId && initialDesign?.is_template !== false ? initialDesign : undefined);
  const setDraft = session.setDraft;
  const saving = saveState.status === "saving";
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [issuesRequest, setIssuesRequest] = useState(0);
  const nameInput = useRef<HTMLInputElement>(null);
  const [inspectorPanel, setInspectorPanel] = useState<InspectorPanel>(null);
  const completed = useCallback((id: string) => { session.discard(initial()); onStarted(id); }, [initial, onStarted, session]);
  const apply = usePipelineApply(`${creationKey}:apply`, completed);
  const locked = !!apply.request || !!apply.operation;
  const canAuthor = props.canEdit && catalog.authoring_enabled && !initialDesign?.archived;
  const busy = saving || loadingTemplate || checking || locked;
  const graph = useGraphEditor({
    document: draft.document, components: catalog.components, readOnly: !canAuthor || locked || checking,
    historyKey: `${creationKey}:history`, onChange: (document) => setDraft((previous) => ({ ...previous, document })),
    onSelect: () => setInspectorPanel("component"),
  });
  const { selected, select, fitRequest, validation, commit, add } = graph;
  const metadata = useGraphMetadata(draft.document.definition, canAuthor, selected);
  const target = targets.find((item) => item.id === draft.targetId);
  const slots = draft.document.definition.input_slots;
  const bindings = Object.fromEntries(slots.filter((slot) => draft.bindings?.[slot.id]).map((slot) => [slot.id, draft.bindings![slot.id]!]));
  const active = new Set(props.services.filter((service) => service.status && service.id !== replaceService?.id).map((service) => service.id));
  const owned = (id: string) => [...(props.byStream.get(id) ?? [])].some((service) => active.has(service));
  const ready = bindingsReady(slots, target, bindings, owned);
  const dirty = session.isDirty();
  useUnsavedChanges(dirty && !locked);

  useEffect(() => {
    if (saveState.status !== "saved") return;
    toast.success("Template saved. You can apply monitoring whenever you are ready.", { id: "pipeline-template-save" });
    session.acknowledge();
  }, [saveState.status, session]);

  const changeInputs = (inputSlots: typeof slots, bindings: Record<string, string>) => {
    commit({ ...draft.document, definition: { ...draft.document.definition, input_slots: inputSlots } });
    setDraft((previous) => ({ ...previous, bindings }));
  };
  const load = (document: GraphDocument, name: string, description: string, bindings?: Record<string, string>) => {
    commit(document);
    session.detachTemplate();
    setDraft((previous) => ({ ...previous, startingId: undefined, name: previous.name || name, description,
      bindings: bindings ?? suggestBindings(document.definition.input_slots, target, previous.bindings) }));
    select(undefined); graph.requestFit();
    toast.success(`Loaded ${name}. Your changes will not affect the original template.`, { id: "pipeline-template-load" });
  };
  const start = async () => {
    if (!canAuthor || busy) return;
    setAttempted(true); setError("");
    if (!draft.name.trim()) { nameInput.current?.focus(); return; }
    if (!ready || !props.collectionReady || props.activationBlocked) return;
    setChecking(true);
    try {
      const result = await graph.validate((definition, selected) => pipelinesApi.validate(definition, undefined, selected));
      if (!result?.valid) { setIssuesRequest((value) => value + 1); setError("Resolve the highlighted processing issues before applying."); return; }
      await apply.session.submit({ definition: draft.document.definition, layout: draft.document.layout,
        bindings, display_name: draft.name.trim(), idempotency_key: crypto.randomUUID(), replace_service_id: replaceId ?? null });
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setChecking(false); }
  };
  const arrange = async () => {
    setArranging(true); setError("");
    try { if (!await graph.arrange()) toast("The graph changed. Arrange again to use the latest edits."); }
    catch (reason) { setError(getErrorMessage(reason)); }
    finally { setArranging(false); }
  };
  return <section className="pl-editor pl-setup" aria-label={initialDesign ? "Pipeline editor" : "Monitoring workbench"}>
    <Breadcrumb disabled={busy} steps={[{ label: props.backLabel ?? "Monitoring", onClick: props.onBack }]}
      current={replaceId ? "Update service" : initialDesign ? initialDesign.name : "New service"} />
    <div className="pl-header pl-setup-header"><div>
      <h1>{replaceId ? "Update monitoring service" : initialDesign ? initialDesign.name : "Create monitoring service"}</h1>
      <p className="pl-help">Choose readings, adjust the flow, and apply. Save a template whenever you want to reuse it.</p>
    </div><div className="pl-actions pl-setup-actions">
      {canAuthor && <>
        <PipelineTemplateMenu catalog={catalog} disabled={busy} onLoading={setLoadingTemplate} onManage={props.onManage} onLoad={load}
          onBuiltIn={(id) => { const item = catalog.templates.find((item) => item.id === id)!;
            const setup = startingSetup(catalog, id, target, initialReading);
            load(setup.document, item.name, "", setup.bindings);
            setDraft((previous) => ({ ...previous, startingId: id })); }} />
        <PipelineSaveTemplate name={template?.name ?? draft.name} description={template?.description ?? draft.description}
          existing={!!template} disabled={busy} saving={saving} error={saveState.message} conflict={saveState.conflict}
          onSave={async (details) => !!await session.save(details)} />
        <button type="button" className="mn-primary" disabled={busy} onClick={() => void start()}>
          <Play size={15} />{checking ? "Checking…" : replaceId ? "Apply changes" : "Apply monitoring"}</button>
      </>}
    </div></div>
    {!canAuthor && <p className="pl-warning" role="status">{initialDesign?.archived ? "This template is archived. Restore it from the template library to edit it."
      : props.canEdit ? "Monitoring configuration is disabled for this deployment." : "An administrator can configure monitoring services."}</p>}
    <>
      {session.restored && dirty && <p className="pl-notice" role="status">Restored your unsaved setup from this browser tab.</p>}
      {error && <p className="pl-error" role="alert">{error}</p>}
      <PipelineApplyStatus apply={apply} />
      <div className="pl-setup-card">
        <div className="pl-setup-fields">
          <label className="pl-field"><span>Service name</span><input ref={nameInput} aria-label="Service name" maxLength={120} placeholder="e.g. Machine health"
            disabled={!canAuthor || locked || checking} aria-invalid={attempted && !draft.name.trim()} aria-describedby={attempted && !draft.name.trim() ? "pl-name-error" : undefined}
            value={draft.name} onChange={(event) => setDraft((previous) => ({ ...previous, name: event.target.value }))} />
            {attempted && !draft.name.trim() && <small className="pl-field-error" id="pl-name-error">Enter a service name.</small>}
          </label>
          <div className="pl-field"><span>Readings from</span><MonitoringTargetPicker targets={targets} value={draft.targetId} disabled={!canAuthor || busy} receivingOnly={false}
            onChange={(targetId) => {
              const next = targets.find((item) => item.id === targetId);
              const matched = draft.startingId ? targetInputs(next, slots, initialReading) : undefined;
              const document = matched ? { ...draft.document, definition: { ...draft.document.definition, input_slots: matched.slots } } : draft.document;
              commit(document);
              setDraft((previous) => ({ ...previous, targetId, bindings: matched?.bindings ?? suggestBindings(document.definition.input_slots, next) }));
            }} /></div>
          <div className="pl-strategy-summary"><span>Learning strategy</span><strong>{draft.document.definition.strategy === "adaptive_stream" ? "Adaptive stream" : "Static baseline"}</strong>
            <small>{draft.document.definition.strategy === "adaptive_stream" ? "Learns from live readings" : "Learns a baseline, then monitors"}</small></div>
        </div>
        {draft.startingId ? <PipelineReadingPicker target={target} selected={Object.values(bindings)} disabled={!canAuthor || locked || checking} owned={owned}
          onChange={(selected) => {
            if (!target) return;
            const next = selectReadings(target, slots, draft.bindings ?? {}, selected);
            changeInputs(next.slots, next.bindings);
          }} />
          : <PipelineInputBindings slots={slots} target={target} bindings={draft.bindings ?? {}} disabled={!canAuthor || locked || checking} owned={owned}
            onChange={(bindings) => setDraft((previous) => ({ ...previous, bindings }))} onSlotsChange={changeInputs} />}
        <div className="pl-setup-card-footer">
          <p className="pl-help">{target ? draft.startingId ? `${Object.keys(bindings).length} readings selected`
            : `${Object.keys(bindings).length} of ${slots.length} inputs mapped` : "Select an entity to choose its readings."}</p>
          <Link to={sourceHref(target?.inputs.map((input) => input.stream.id) ?? [], catalogueDocument, `${location.pathname}${location.search}`)}>Configure readings in Sources</Link>
        </div>
        {attempted && !ready && <p className="pl-field-error" role="alert">{draft.startingId ? "Select at least one available reading to monitor."
          : "Choose a different, collected reading for each input. Readings already monitored by another service are unavailable."}</p>}
        {!props.collectionReady && <p className="pl-help" role="status">Enable collection in Sources and wait for it to connect before applying monitoring.</p>}
        {props.activationBlocked && !locked && <p className="pl-warning" role="status">{props.activationBlocked}</p>}
        {replaceId && !locked && <p className="pl-warning">Applying changes replaces “{replaceService?.display_name ?? "the selected service"}”. Monitoring pauses briefly and learning starts again. Its history is kept.</p>}
      </div>
      <PipelineWorkbench catalog={catalog} document={draft.document} validation={metadata ?? validation} readOnly={!canAuthor || locked || checking}
        inspectorPanel={inspectorPanel} onInspectorPanelChange={setInspectorPanel}
        selected={selected} fitRequest={fitRequest} reveal={graph.reveal} onSelect={select} onChange={commit} onAdd={add}
        onBeginMove={graph.beginMove} onUndo={graph.undo} onRedo={graph.redo} issuesRequest={issuesRequest}
        actions={canAuthor && !locked && <>
          <button type="button" disabled={!graph.canUndo} aria-label="Undo graph change" title="Undo (Ctrl+Z)" onClick={graph.undo}><Undo2 size={15} /></button>
          <button type="button" disabled={!graph.canRedo} aria-label="Redo graph change" title="Redo (Ctrl+Shift+Z)" onClick={graph.redo}><Redo2 size={15} /></button>
          <button type="button" disabled={arranging} onClick={() => void arrange()}><LayoutGrid size={15} />Arrange</button>
          <button type="button" disabled={checking} onClick={async () => {
            try { await graph.validate((definition, selected) => pipelinesApi.validate(definition, undefined, selected)); setIssuesRequest((value) => value + 1); }
            catch (reason) { setError(getErrorMessage(reason)); }
          }}><Check size={15} />Validate</button>
          {dirty && <button type="button" title="Reset to the initial configuration" onClick={async () => {
            if (!await confirm({ title: "Discard this setup?", description: "Your changes to this flow are cleared and the setup starts again.",
              confirmLabel: "Discard and start again", destructive: true })) return;
            session.discard(initial()); graph.resetHistory(); select(undefined); graph.requestFit(); setAttempted(false);
          }}><RotateCcw size={15} />Reset</button>}
        </>}
        settings={<PipelineDesignSettings document={draft.document} readOnly={!canAuthor || locked || checking} onChange={(document, history) => {
          commit(document, history);
          if (document.definition.input_slots !== slots) setDraft((previous) => ({ ...previous, startingId: undefined }));
        }} />} />
    </>
    {confirmation}
  </section>;
}
