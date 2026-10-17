import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, LayoutGrid, Redo2, Save, Undo2 } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import { rememberNavigation, useNavigationDraft } from "@/lib/navigation-draft";
import { MonitoringTargetPicker } from "../monitoring/MonitoringTargetPicker";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import { sourceHref } from "../catalogue/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import { normalizeDefinition, normalizeLayout, type PipelineCatalog, type PipelineValidation } from "./contracts";
import { addComponent, type GraphDocument } from "./model";
import { acknowledgeSave, type EditorDraft } from "./editorSession";
import { pipelinesApi } from "./api";
import { arrangeGraph } from "./layout";
import { useGraphMetadata } from "./useGraphMetadata";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineTemplateMenu } from "./PipelineTemplateMenu";
import { PipelineWorkbench } from "./PipelineWorkbench";

type CreationDraft = EditorDraft & { targetId?: string; startingId?: string };

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
  const initial = (): CreationDraft => ({
    name: "", description: "", targetId: initialTarget, startingId,
    document: startingDocument(catalog, startingId, targets.find((item) => item.id === initialTarget), initialReading),
  });
  const [draft, setDraft] = useNavigationDraft<CreationDraft>(
    `pipeline-create:${userId}:${initialTarget ?? ""}:${initialReading ?? ""}`, initial,
  );
  const current = useRef(draft);
  useEffect(() => { current.current = draft; }, [draft]);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const [saving, setSaving] = useState(false);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string>();
  const [inspectorPanel, setInspectorPanel] = useState<"service" | "component">("service");
  const [fitRequest, setFitRequest] = useState(0);
  const [undo, setUndo] = useState<GraphDocument[]>([]);
  const [redo, setRedo] = useState<GraphDocument[]>([]);
  const [mobilePanel, setMobilePanel] = useState<"graph" | "components" | "inspector">("graph");
  const [validation, setValidation] = useState<PipelineValidation>();
  const canAuthor = canEdit && catalog.authoring_enabled;
  const metadata = useGraphMetadata(undefined, draft.document.definition, canAuthor, selected);
  const target = targets.find((item) => item.id === draft.targetId);
  const busy = saving || loadingTemplate;

  useEffect(() => {
    if (!draft.name && !draft.description && draft.startingId && !undo.length) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [draft.name, draft.description, draft.startingId, undo.length]);

  const commit = (document: GraphDocument, recordHistory = true) => {
    if (recordHistory) {
      setUndo((previous) => [...previous.slice(-39), draft.document]);
      setRedo([]);
    }
    setDraft((previous) => ({ ...previous, document,
      startingId: previous.document.definition === document.definition ? previous.startingId : undefined }));
    setValidation(undefined);
    setNotice("");
  };
  const select = (id: string) => { setSelected(id); setInspectorPanel("component"); setMobilePanel("inspector"); };
  const add = (id: string, position?: { x: number; y: number }) => {
    const component = catalog.components.find((item) => item.id === id);
    if (!component) return;
    const next = addComponent(draft.document, component);
    if (next === draft.document) return;
    const node = next.definition.nodes[next.definition.nodes.length - 1]!;
    if (position) next.layout.nodes[node.id] = { ...next.layout.nodes[node.id], ...position };
    commit(next);
    select(node.id);
  };
  const load = (document: GraphDocument, name: string, description: string, version: string) => {
    commit(document);
    setDraft((previous) => ({ ...previous, name: previous.name || `${name.slice(0, 113)} (copy)`, description }));
    setSelected(undefined);
    setFitRequest((value) => value + 1);
    setNotice(`Loaded ${name} · ${version}. You are editing a separate design.`);
  };
  const save = async () => {
    if (!canAuthor || pending.current) return;
    if (!draft.name.trim()) { setError("Enter a service name in Service settings before saving."); setInspectorPanel("service"); setMobilePanel("inspector"); return; }
    const controller = new AbortController();
    pending.current = controller;
    const submitted = draft;
    setSaving(true); setError("");
    try {
      const saved = await pipelinesApi.create({ name: submitted.name.trim(), description: submitted.description,
        definition: submitted.document.definition, layout: submitted.document.layout });
      if (controller.signal.aborted) return;
      // Carry edits made during the request into the persisted editor's session.
      const { document, name, description } = current.current;
      rememberNavigation(`pipeline:${userId}:${saved.id}`, acknowledgeSave({ document, name, description }, submitted, saved));
      setDraft(initial());
      onCreated(saved.id, current.current.targetId);
    } catch (reason) {
      if (!controller.signal.aborted) setError(getErrorMessage(reason));
    } finally {
      if (!controller.signal.aborted) { pending.current = null; setSaving(false); }
    }
  };
  const validate = async () => {
    if (validating) return;
    setValidating(true);
    setError("");
    try {
      const submitted = draft.document;
      const report = await pipelinesApi.validate(undefined, submitted.definition, undefined, selected);
      if (current.current.document === submitted) setValidation(report);
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setValidating(false); }
  };
  const arrange = async () => {
    setArranging(true); setError("");
    try {
      const submitted = draft.document;
      const layout = await arrangeGraph(submitted.definition, submitted.layout);
      if (current.current.document !== submitted) { setNotice("The graph changed while arranging. Arrange again to use the latest edits."); return; }
      commit({ ...submitted, layout });
      setFitRequest((value) => value + 1);
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setArranging(false); }
  };

  return <section className={`pl-editor pl-mobile--${mobilePanel}`} aria-label="Monitoring workbench">
    <button type="button" className="mn-back" disabled={busy} onClick={onBack}><ArrowLeft size={14} />Monitoring</button>
    <div className="pl-header"><div><h2>Create monitoring service</h2>
      <p className="pl-help">Build your processing flow. Select a component to configure it in the inspector.</p>
    </div><div className="pl-actions">
      {canAuthor && <>
        <PipelineTemplateMenu catalog={catalog} disabled={saving} onLoading={setLoadingTemplate} onManage={onManage}
          onLoad={load} onBuiltIn={(id) => {
            const template = catalog.templates.find((item) => item.id === id)!;
            commit(startingDocument(catalog, id, target, initialReading));
            setDraft((previous) => ({ ...previous, startingId: id }));
            setSelected(undefined); setFitRequest((value) => value + 1);
            setNotice(`Loaded ${template.name}. Undo restores your previous flow.`);
          }} />
        <button type="button" disabled={busy || validating} onClick={() => void validate()}><Check size={15} />Validate</button>
        <button type="button" className="mn-primary" disabled={busy || validating} onClick={() => void save()}><Save size={15} />Save draft</button>
      </>}
    </div></div>
    {!canAuthor ? <p className="pl-warning" role="status">{canEdit ? "Design authoring is disabled for this deployment."
      : "An administrator can create monitoring services."}</p> : <>
      {error && <p className="pl-error" role="alert">{error}</p>}
      {notice && <p className="pl-notice" role="status">{notice}</p>}
      <div className="pl-canvas-toolbar">
        <div className="pl-mobile-switch" aria-label="Workbench panel">{(["graph", "components", "inspector"] as const).map((panel) =>
          <button type="button" key={panel} aria-pressed={mobilePanel === panel} onClick={() => setMobilePanel(panel)}>{panel}</button>)}</div>
        <div className="pl-actions">
          <button type="button" disabled={!undo.length} aria-label="Undo graph change" onClick={() => {
            const next = undo[undo.length - 1]!; setRedo((previous) => [...previous, draft.document]);
            setUndo((previous) => previous.slice(0, -1)); setDraft((previous) => ({ ...previous, document: next, startingId: undefined })); setValidation(undefined); setNotice("");
          }}><Undo2 size={15} />Undo</button>
          <button type="button" disabled={!redo.length} aria-label="Redo graph change" onClick={() => {
            const next = redo[redo.length - 1]!; setUndo((previous) => [...previous, draft.document]);
            setRedo((previous) => previous.slice(0, -1)); setDraft((previous) => ({ ...previous, document: next, startingId: undefined })); setValidation(undefined); setNotice("");
          }}><Redo2 size={15} />Redo</button>
          <button type="button" disabled={arranging} onClick={() => void arrange()}><LayoutGrid size={15} />Arrange</button>
        </div>
      </div>
      <PipelineWorkbench catalog={catalog} document={draft.document} validation={metadata ?? validation}
        inspectorPanel={inspectorPanel} onInspectorPanelChange={setInspectorPanel}
        selected={selected} fitRequest={fitRequest} onSelect={select} onChange={commit} onAdd={add}
        onBeginMove={() => { setUndo((previous) => [...previous.slice(-39), draft.document]); setRedo([]); }}
        settings={<>
          <h3>Service settings</h3>
          <label className="pl-field"><span>Service name</span><input maxLength={120} placeholder="e.g. Machine health"
            value={draft.name} onChange={(event) => setDraft((previous) => ({ ...previous, name: event.target.value }))} /></label>
          <div className="pl-field"><span>Inputs</span><MonitoringTargetPicker targets={targets} value={draft.targetId} disabled={busy}
            onChange={(targetId) => {
              if (draft.startingId) {
                const next = startingDocument(catalog, draft.startingId, targets.find((item) => item.id === targetId), initialReading);
                setUndo((previous) => [...previous.slice(-39), draft.document]); setRedo([]);
                setDraft((previous) => ({ ...previous, targetId, document: { ...previous.document,
                  definition: { ...previous.document.definition, input_slots: next.definition.input_slots } } }));
                setValidation(undefined);
              } else setDraft((previous) => ({ ...previous, targetId }));
            }} /></div>
          <p className="pl-help">{draft.document.definition.strategy === "adaptive_stream" ? "Adaptive stream" : "Static baseline"}
            {" · "}Use Templates to choose another starting flow.</p>
          {target && <p className="pl-help"><Link to={sourceHref(target.inputs.map((input) => input.stream.id), catalogueDocument,
            `${location.pathname}${location.search}`)}>Configure readings in Sources</Link></p>}
          <PipelineDesignSettings document={draft.document} readOnly={false} onChange={commit} />
          <p className="pl-help">Save your draft to publish a revision and review input bindings before starting.</p>
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
