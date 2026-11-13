import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { LayoutGrid, Play, Redo2, RotateCcw, Undo2 } from "lucide-react";
import { Breadcrumb } from "@/components/Breadcrumb";
import { useConfirm } from "@/hooks/use-confirm";
import { useDetailDocumentTitle } from "@/hooks/use-document-title";
import { Link, useLocation } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import { MonitoringTargetPicker } from "../workspace/MonitoringTargetPicker";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { sourceHref } from "@/domain/system/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import { normalizeDefinition, normalizeLayout, type PipelineCatalog, type PipelineServiceView, type PipelineView } from "./contracts";
import type { GraphDocument } from "./model";
import { useCreationSession, type CreationDraft } from "./creationSession";
import { pipelinesApi } from "./api";
import { useGraphMetadata } from "./useGraphMetadata";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useGraphEditor } from "./useGraphEditor";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineTemplateMenu } from "./PipelineTemplateMenu";
import { PipelineSaveTemplate } from "./PipelineSaveTemplate";
import { PipelineWorkbench, type InspectorPanel } from "./PipelineWorkbench";
import { PipelineInputBindings } from "./PipelineInputBindings";
import { PipelineReadingPicker } from "./PipelineReadingPicker";
import { PipelineApplyStatus } from "./PipelineApplyStatus";
import { usePipelineApply } from "./applySession";
import { bindingsReady, predecessorTarget, previousBindings, readingOwnedElsewhere, suggestBindings, suggestedTarget } from "./bindings";
import { selectReadings, targetInputs } from "./slots";
import { learningWindow } from "./learning";
import { starterTemplate, withoutDetector } from "./detectorSlot";
import { startupEstimate } from "./startup";

export type PipelineSetupProps = {
  catalog: PipelineCatalog; canEdit: boolean; targets: MonitoringTarget[];
  services: ActiveService[]; byStream: Map<string, Set<string>>; collectionReady: boolean;
  initialTarget?: string; initialReading?: string; initialDesign?: PipelineView;
  /** Readings suggested per slot, for example the ones a Dojo run tested the design on. */
  initialBindings?: Record<string, string>;
  initialDocument?: GraphDocument; replaceService?: ActiveService; predecessor?: PipelineServiceView;
  revisionId?: string;
  sourceService?: { id: string; replace: boolean };
  activationBlocked?: string; onManage: () => void; onBack: () => void; onStarted: (id: string) => void;
  /** Names where onBack leads, for the breadcrumb. */
  backLabel?: string;
  /** Extra controls beside the setup's actions, such as a template's archive option. */
  menu?: ReactNode;
};

function startingSetup(catalog: PipelineCatalog, id?: string, target?: MonitoringTarget, reading?: string) {
  const template = catalog.templates.find((item) => item.id === id) ?? catalog.templates[0];
  const inputs = targetInputs(target, reading);
  return { document: { definition: template ? { ...template.definition,
    input_slots: inputs?.slots ?? template.definition.input_slots } : normalizeDefinition({}), layout: template?.layout ?? normalizeLayout() },
  bindings: inputs?.bindings ?? {} };
}

const inputNode = (document: GraphDocument) => document.definition.nodes.find((node) => node.kind === "source")?.id;

/** The same setup surface configures a new service, a template or a replacement. */
export function PipelineCreate(props: PipelineSetupProps) {
  const { catalog, targets, initialTarget, initialReading, initialDesign, initialDocument, initialBindings, replaceService, predecessor, onStarted } = props;
  const { userId } = useAuth();
  const { document: catalogueDocument, system } = useCatalogue();
  const [confirm, confirmation] = useConfirm();
  const location = useLocation();
  const replaceId = props.sourceService?.replace ? props.sourceService.id : replaceService?.id;
  const sourceId = props.sourceService?.id ?? replaceId;
  // A new service starts from the flow that learns from the stream, with its detector left to choose.
  const startingId = starterTemplate(catalog)?.id;
  const initial = useCallback((): CreationDraft => {
    const suggested = { ...initialBindings, ...previousBindings(predecessor) };
    const targetId = initialTarget ?? predecessorTarget(targets, predecessor) ?? suggestedTarget(targets, suggested);
    const target = targets.find((item) => item.id === targetId);
    const starting = startingSetup(catalog, startingId, target, initialReading);
    const document = initialDocument ?? (initialDesign
      ? { definition: initialDesign.draft, layout: initialDesign.layout }
      : withoutDetector(starting.document));
    return { name: replaceService?.display_name ?? initialDesign?.name ?? "", description: initialDesign?.description ?? "",
      targetId, startingId: initialDesign || initialDocument ? undefined : startingId, document,
      bindings: initialDesign || initialDocument ? suggestBindings(document.definition.input_slots, target,
        suggested) : starting.bindings };
  }, [catalog, initialBindings, initialDesign, initialDocument, initialReading, initialTarget, predecessor, replaceService, startingId, targets]);
  const creationKey = `pipeline-setup:${userId}:${initialDesign?.id ?? "new"}:${props.revisionId ?? "draft"}:${sourceId ?? initialTarget ?? ""}:${replaceId ? "replace" : "new"}:${initialReading ?? ""}:${Object.entries(initialBindings ?? {}).join(";")}`;
  const { draft, template, save: saveState, session } = useCreationSession(creationKey, initial,
    !replaceId && !props.revisionId && initialDesign?.is_template !== false ? initialDesign : undefined);
  const viewTitle = replaceId ? "Update service" : initialDesign ? "Template" : "New service";
  useDetailDocumentTitle(draft.name.trim() ? `${draft.name} — ${viewTitle}` : viewTitle, "Monitoring");
  const setDraft = session.setDraft;
  const saving = saveState.status === "saving";
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [issuesRequest, setIssuesRequest] = useState(0);
  const nameInput = useRef<HTMLInputElement>(null);
  // A new service starts at its readings; a saved design or a replacement starts at its graph.
  const [opensAtInput] = useState(!initialDesign && !initialDocument && !replaceId);
  const [inspectorPanel, setInspectorPanel] = useState<InspectorPanel>(opensAtInput ? "component" : null);
  const completed = useCallback((id: string) => { session.discard(initial()); onStarted(id); }, [initial, onStarted, session]);
  const apply = usePipelineApply(`${creationKey}:apply`, completed);
  const locked = !!apply.request || !!apply.operation;
  const canAuthor = props.canEdit && catalog.authoring_enabled && !initialDesign?.archived;
  const busy = saving || loadingTemplate || checking || locked;
  const graph = useGraphEditor({
    document: draft.document, components: catalog.components, readOnly: !canAuthor || locked || checking,
    historyKey: `${creationKey}:history`, onChange: (document) => setDraft((previous) => ({ ...previous, document })),
    onSelect: () => setInspectorPanel("component"), initialSelected: opensAtInput ? inputNode(draft.document) : undefined,
  });
  const { selected, select, fitRequest, validation, commit, add } = graph;
  const metadata = useGraphMetadata(draft.document.definition, canAuthor, selected);
  const compiledValidation = metadata.validation ?? validation;
  const runtimeIssues = apply.operation?.issues ?? [];
  const displayedValidation = compiledValidation && runtimeIssues.length
    ? { ...compiledValidation, valid: false, issues: [...compiledValidation.issues, ...runtimeIssues] }
    : compiledValidation;
  const target = targets.find((item) => item.id === draft.targetId);
  const inputsForTarget = target?.inputs ?? [];
  const unrecorded = inputsForTarget.filter(input => input.binding.policy.mode === "off").map(input => input.stream.id);
  const waitingForRecording = !props.collectionReady && (!unrecorded.length || unrecorded.length < inputsForTarget.length);
  const recordingIds = !waitingForRecording && unrecorded.length ? unrecorded : inputsForTarget.map(input => input.stream.id);
  const recordingHref = sourceHref(initialReading && recordingIds.includes(initialReading) ? [initialReading] : recordingIds,
    catalogueDocument, `${location.pathname}${location.search}`);
  const slots = draft.document.definition.input_slots;
  const bindings = Object.fromEntries(slots.filter((slot) => draft.bindings?.[slot.id]).map((slot) => [slot.id, draft.bindings![slot.id]!]));
  const validateGraph = () => graph.validate((definition, selected) => pipelinesApi.validate(definition, undefined, selected));
  const owned = readingOwnedElsewhere(props.services, props.byStream, replaceService?.id);
  const ready = bindingsReady(slots, target, bindings, owned);
  const dirty = session.isDirty();
  const mapped = Object.keys(bindings).length;
  const readingCount = draft.startingId ? `${mapped} ${mapped === 1 ? "reading" : "readings"}` : `${mapped} of ${slots.length} readings`;
  const intervals = system.snapshot?.runtime.ingress?.readings;
  const startup = startupEstimate(draft.document.definition,
    Object.values(bindings).map((reading) => intervals?.[reading]?.typical_interval_seconds),
    compiledValidation?.preparation_observations,
    learningWindow(draft.document.definition, catalog.components));
  const openInput = () => { const id = inputNode(draft.document); if (id) select(id); };
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
  // The reading this setup was opened from is preselected as soon as it can be
  // monitored, also when its recording was turned on after the setup opened.
  const picked = useRef(false);
  const contextReady = !!draft.startingId && !!target && !!initialReading && !Object.keys(bindings).length
    && target.inputs.some((input) => input.stream.id === initialReading && input.binding.policy.mode !== "off" && !owned(input.stream.id));
  useEffect(() => {
    if (!contextReady || picked.current || !canAuthor || locked) return;
    picked.current = true;
    const next = selectReadings(target!, slots, draft.bindings ?? {}, [initialReading!]);
    changeInputs(next.slots, next.bindings);
  });
  const load = (document: GraphDocument, name: string, description: string, bindings?: Record<string, string>) => {
    commit(document);
    session.detachTemplate();
    setDraft((previous) => ({ ...previous, startingId: undefined, name: previous.name || name, description,
      bindings: bindings ?? suggestBindings(document.definition.input_slots, target, previous.bindings) }));
    // A new service goes on to its readings; a design's own editor returns to the graph.
    select(opensAtInput ? inputNode(document) : undefined); graph.requestFit();
    toast.success(`Loaded ${name}. Your changes will not affect the original template.`, { id: "pipeline-template-load" });
  };
  const start = async () => {
    if (!canAuthor || busy) return;
    setAttempted(true); setError("");
    if (!draft.name.trim()) { nameInput.current?.focus(); return; }
    if (!ready) { openInput(); return; }
    if (!props.collectionReady || props.activationBlocked) return;
    setChecking(true);
    try {
      const result = await validateGraph();
      // What is left to do opens as a list beside the status, where each entry leads to its step.
      if (!result?.valid) { setIssuesRequest((value) => value + 1); return; }
      await apply.session.submit({ definition: draft.document.definition, layout: draft.document.layout,
        bindings, display_name: draft.name.trim(), idempotency_key: crypto.randomUUID(), replace_monitor_id: replaceId ?? null });
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setChecking(false); }
  };
  const arrange = async () => {
    setArranging(true); setError("");
    try { if (!await graph.arrange()) toast("The graph changed. Arrange again to use the latest edits."); }
    catch (reason) { setError(getErrorMessage(reason)); }
    finally { setArranging(false); }
  };
  const title = replaceId ? "Update monitoring service" : initialDesign ? initialDesign.name : "Create monitoring service";
  const inputStep = <div className="pl-input-step">
    <div className="pl-field"><span>Readings from</span><MonitoringTargetPicker targets={targets} value={draft.targetId} disabled={!canAuthor || busy}
      // A service starts on live sources; a template may be mapped to any entity.
      receivingOnly={!initialDesign}
      onChange={(targetId) => {
        const next = targets.find((item) => item.id === targetId);
        const matched = draft.startingId ? targetInputs(next, initialReading) : undefined;
        const document = matched ? { ...draft.document, definition: { ...draft.document.definition, input_slots: matched.slots } } : draft.document;
        commit(document);
        setDraft((previous) => ({ ...previous, targetId, bindings: matched?.bindings ?? suggestBindings(document.definition.input_slots, next) }));
      }} /></div>
    {draft.startingId ? <PipelineReadingPicker target={target} selected={Object.values(bindings)} disabled={!canAuthor || locked || checking} owned={owned}
      onChange={(selected) => {
        if (!target) return;
        picked.current = true;
        const next = selectReadings(target, slots, draft.bindings ?? {}, selected);
        changeInputs(next.slots, next.bindings);
      }} />
      : <PipelineInputBindings slots={slots} target={target} bindings={draft.bindings ?? {}} disabled={!canAuthor || locked || checking} owned={owned}
        onChange={(bindings) => setDraft((previous) => ({ ...previous, bindings }))} onSlotsChange={changeInputs} />}
    {attempted && !ready && (!unrecorded.length || unrecorded.length < inputsForTarget.length) && <p className="pl-field-error" role="alert">{draft.startingId ? "Select at least one available reading to monitor."
      : "Choose a different, collected reading for each input. Readings already monitored by another service are unavailable."}</p>}
    <div className="pl-input-step-footer">
      <p className="pl-help">{target ? draft.startingId ? `${mapped} ${mapped === 1 ? "reading" : "readings"} selected`
        : `${mapped} of ${slots.length} inputs mapped` : "Select an entity to choose its readings."}</p>
      {target && props.collectionReady && !unrecorded.length && <Link to={recordingHref}>Review recording in Sources</Link>}
    </div>
  </div>;
  // One line names the service: where it sits, its name and what it monitors.
  const header = <>
    <header className="pl-header pl-setup-header">
      <div className="pl-setup-identity">
        <Breadcrumb disabled={busy} steps={[{ label: props.backLabel ?? "Monitoring", onClick: props.onBack }]}
          current={replaceId ? "Update service" : initialDesign ? initialDesign.name : "New service"} />
        <h1 className="ex-sr-only">{title}</h1>
        <input ref={nameInput} className="pl-name-input" aria-label="Service name" maxLength={120} placeholder="Name this service"
          disabled={!canAuthor || locked || checking} aria-invalid={attempted && !draft.name.trim()} aria-describedby={attempted && !draft.name.trim() ? "pl-name-error" : undefined}
          value={draft.name} onChange={(event) => setDraft((previous) => ({ ...previous, name: event.target.value }))} />
        <button type="button" className="pl-setup-input" aria-label={target ? `Input: ${target.label}, ${readingCount}` : "Input: choose readings"}
          title="Choose readings" onClick={openInput}>
          {target ? `${target.label} · ${readingCount}` : "Choose readings"}
        </button>
        {attempted && !draft.name.trim() && <small className="pl-field-error" id="pl-name-error">Enter a service name.</small>}
      </div>
      {(canAuthor || props.menu) && <div className="pl-actions pl-setup-actions">
        {canAuthor && <>
          <PipelineTemplateMenu catalog={catalog} disabled={busy} onLoading={setLoadingTemplate} onManage={props.onManage} onLoad={load}
            onBuiltIn={(id) => { const item = catalog.templates.find((item) => item.id === id)!;
              const setup = startingSetup(catalog, id, target, initialReading);
              load(setup.document, item.name, "", setup.bindings);
              setDraft((previous) => ({ ...previous, startingId: id })); }} />
          <PipelineSaveTemplate name={template?.name ?? draft.name} description={template?.description ?? draft.description}
            existing={!!template} disabled={busy} saving={saving} error={saveState.message} conflict={saveState.conflict}
            onSave={async (details) => !!await session.save(details)} />
        </>}
        {props.menu}
        {canAuthor && <button type="button" className="mn-primary" disabled={busy} onClick={() => void start()}>
          <Play size={15} />{checking ? "Checking…" : replaceId ? "Update monitoring" : "Start monitoring"}</button>}
      </div>}
    </header>
    <div className="pl-setup-notices">
      {!canAuthor && <p className="pl-warning" role="status">{initialDesign?.archived ? "This template is archived. Restore it from the template library to edit it."
        : props.canEdit ? "Monitoring configuration is disabled for this deployment." : "Configuring monitoring services needs the Manage monitors permission."}</p>}
      {session.restored && dirty && <p className="pl-notice" role="status">Restored your unsaved setup from this browser tab.</p>}
      {error && <p className="pl-error" role="alert">{error}</p>}
      <PipelineApplyStatus apply={apply} onInspect={id => { select(id); setInspectorPanel("component"); }} />
      {waitingForRecording ? <p className="pl-warning" role="status">Waiting for recording settings to apply.
        {target && <> <Link to={recordingHref}>Review recording in Sources</Link></>}
      </p>
        : unrecorded.length > 0 && <p className="pl-notice" role="status">
          Recording is off for {unrecorded.length} {unrecorded.length === 1 ? "reading" : "readings"}.{" "}
          <Link to={recordingHref}>Turn on recording in Sources</Link>
        </p>}
      {props.activationBlocked && !locked && <p className="pl-warning" role="status">{props.activationBlocked}</p>}
      {replaceId && !locked && <p className="pl-warning">Updating replaces “{replaceService?.display_name ?? "the selected service"}”. Monitoring pauses briefly and learning restarts. History is kept.</p>}
    </div>
  </>;
  return <section className="pl-editor pl-setup" aria-label={initialDesign ? "Pipeline editor" : "Monitoring workbench"}>
    <PipelineWorkbench stage header={header} catalog={catalog} document={draft.document} validation={displayedValidation} readOnly={!canAuthor || locked || checking}
      inspectorPanel={inspectorPanel} onInspectorPanelChange={setInspectorPanel} input={inputStep} startup={startup}
      validationError={metadata.error} onRetryValidation={metadata.retry}
      selected={selected} fitRequest={fitRequest} reveal={graph.reveal} onSelect={select} onChange={commit} onAdd={add}
      onPlace={graph.place}
      onBeginMove={graph.beginMove} onUndo={graph.undo} onRedo={graph.redo} issuesRequest={issuesRequest}
      actions={canAuthor && !locked && <>
        <button type="button" disabled={!graph.canUndo} aria-label="Undo graph change" title="Undo (Ctrl+Z)" onClick={graph.undo}><Undo2 size={15} /></button>
        <button type="button" disabled={!graph.canRedo} aria-label="Redo graph change" title="Redo (Ctrl+Shift+Z)" onClick={graph.redo}><Redo2 size={15} /></button>
        <button type="button" disabled={arranging} onClick={() => void arrange()}><LayoutGrid size={15} />Arrange</button>
        {dirty && <button type="button" title="Reset to the initial configuration" onClick={async () => {
          if (!await confirm({ title: "Discard this setup?", description: "Your changes to this flow are cleared and the setup starts again.",
            confirmLabel: "Discard and start again", destructive: true })) return;
          const fresh = initial();
          session.discard(fresh); graph.resetHistory(); select(opensAtInput ? inputNode(fresh.document) : undefined); graph.requestFit(); setAttempted(false);
        }}><RotateCcw size={15} />Reset</button>}
      </>}
      settings={<PipelineDesignSettings document={draft.document} catalog={catalog} startup={startup} readOnly={!canAuthor || locked || checking}
        onChange={(document, history) => {
          commit(document, history);
          if (document.definition.input_slots !== slots) setDraft((previous) => ({ ...previous, startingId: undefined }));
        }} />} />
    {confirmation}
  </section>;
}
