import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  GitBranch,
  LayoutGrid,
  Redo2,
  Save,
  Undo2,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import type {
  PipelineCatalog,
  PipelineServiceView,
  PipelineValidation,
  PipelineView,
} from "./contracts";
import PipelineCanvas from "./PipelineCanvas";
import { arrangeGraph } from "./layout";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineToolbox } from "./PipelineToolbox";
import { PipelineDesignSettings } from "./PipelineDesignSettings";
import { PipelineActivation } from "./PipelineActivation";
import { addComponent, executableChanges, type GraphDocument } from "./model";
import { pipelinesApi } from "./api";
import { useGraphMetadata } from "./useGraphMetadata";
import { usePipelineRevisions } from "./usePipelineRevisions";
import {
  acknowledgeSave,
  isSessionDirty,
  openSession,
  type EditorSession as Session,
} from "./editorSession";

type Props = {
  id: string;
  catalog: PipelineCatalog;
  canEdit: boolean;
  targets: MonitoringTarget[];
  services: ActiveService[];
  byStream: Map<string, Set<string>>;
  initialTarget?: string;
  initialReading?: string;
  collectionReady: boolean;
  revisionId?: string;
  activationId?: string;
  replaceService?: ActiveService;
  predecessor?: PipelineServiceView;
  activationBlocked?: string;
  onBack: () => void;
  onOpen: (id: string) => void;
  onRevision: (id?: string) => void;
  onOperation: (id: string) => void;
  onStarted: (id: string) => void;
};

export default function PipelineEditor(props: Props) {
  const [pipeline, setPipeline] = useState<PipelineView>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi
      .get(props.id, controller.signal)
      .then(setPipeline, (reason) => {
        if (!controller.signal.aborted) setError(getErrorMessage(reason));
      });
    return () => controller.abort();
  }, [props.id, retry]);
  if (!pipeline)
    return (
      <section aria-label="Pipeline editor">
        <button className="mn-back" onClick={props.onBack}>
          Pipeline library
        </button>
        {error ? (
          <p className="pl-error" role="alert">
            {error}
            <button onClick={() => setRetry((value) => value + 1)}>
              Retry
            </button>
          </p>
        ) : (
          <p role="status">Loading pipeline…</p>
        )}
      </section>
    );
  return <EditorSession key={pipeline.id} {...props} initial={pipeline} />;
}

function EditorSession({
  initial,
  ...props
}: Props & { initial: PipelineView }) {
  const { userId } = useAuth();
  const [session, setSession] = useNavigationDraft<Session>(
    `pipeline:${userId}:${initial.id}`,
    () => openSession(initial),
  );
  const [selected, setSelected] = useState<string>();
  const currentSession = useRef(session);
  useEffect(() => {
    currentSession.current = session;
  }, [session]);
  const [validation, setValidation] = useState<PipelineValidation>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(
    initial.version !== session.base.version,
  );
  const [showActivation, setShowActivation] = useState(
    !!props.activationId ||
      (!!props.revisionId && session.activationRevisionId === props.revisionId),
  );
  const review = (open: boolean) => {
    setShowActivation(open);
    setSession((current) => ({
      ...current,
      activationRevisionId: open ? props.revisionId : undefined,
    }));
  };
  const [undo, setUndo] = useState<GraphDocument[]>([]);
  const [redo, setRedo] = useState<GraphDocument[]>([]);
  const [mobilePanel, setMobilePanel] = useState<
    "graph" | "components" | "inspector"
  >("graph");
  const base = session.base;
  const revisions = usePipelineRevisions(base, props.revisionId);
  const revision = revisions.revision;
  const document = revision
    ? { definition: revision.definition, layout: session.document.layout }
    : session.document;
  const canWrite =
    props.canEdit && props.catalog.authoring_enabled && !base.archived;
  const readOnly = !canWrite || !!props.revisionId;
  const metadata = useGraphMetadata(
    base.id,
    document.definition,
    !readOnly || !!revision,
    selected,
    revision?.id,
  );
  const dirty = isSessionDirty(session);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);
  const commit = (next: GraphDocument, recordHistory = true) => {
    if (recordHistory) {
      setUndo((previous) => [...previous.slice(-39), session.document]);
      setRedo([]);
    }
    if (next.definition !== session.document.definition)
      setValidation(undefined);
    setNotice("");
    setSession((previous) => ({ ...previous, document: next }));
  };
  const report = (reason: unknown) => {
    setError(getErrorMessage(reason));
    if (reason instanceof ApiRequestError && reason.status === 409)
      setConflict(true);
  };
  const save = async (): Promise<PipelineView> => {
    const submitted = session;
    const saved = await pipelinesApi.save(base.id, {
      expected_version: base.version,
      definition: submitted.document.definition,
      layout: submitted.document.layout,
      name: submitted.name.trim(),
      description: submitted.description,
    });
    setSession((current) => acknowledgeSave(current, submitted, saved));
    setConflict(false);
    setNotice("Draft saved.");
    return saved;
  };
  const action = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (reason) {
      report(reason);
    } finally {
      setBusy(false);
    }
  };
  const publish = () =>
    action(async () => {
      const result = await pipelinesApi.validate(
        base.id,
        session.document.definition,
        undefined,
        selected,
      );
      setValidation(result);
      if (!result.valid) {
        setError("Resolve graph validation errors before publishing.");
        return;
      }
      const saved = dirty ? await save() : base;
      const published = await pipelinesApi.publish(base.id, {
        expected_version: saved.version,
      });
      const latest = await pipelinesApi.get(base.id);
      setSession((previous) => ({ ...previous, base: latest }));
      props.onRevision(published.id);
      setNotice(
        `Revision ${published.number} published. Existing runs keep their current revision.`,
      );
    });
  const add = (id: string, position?: { x: number; y: number }) => {
    const component = props.catalog.components.find((item) => item.id === id);
    if (!component || readOnly) return;
    const next = addComponent(document, component);
    if (next === document) return;
    const added = next.definition.nodes[next.definition.nodes.length - 1]!;
    if (position)
      next.layout.nodes[added.id] = {
        ...next.layout.nodes[added.id],
        ...position,
      };
    commit(next);
    setSelected(added.id);
    setMobilePanel("inspector");
  };
  const select = (id: string) => {
    setSelected(id);
    setMobilePanel("inspector");
  };
  const changes = revision
    ? executableChanges(
        revision.definition,
        session.document.definition,
        props.catalog.components,
      )
    : [];
  if (props.revisionId && !revision)
    return (
      <section aria-label="Pipeline editor">
        {revisions.error ? (
          <p className="pl-error" role="alert">
            Published revision could not load. {revisions.error}
          </p>
        ) : (
          <p role="status">Loading published revision…</p>
        )}
        {revisions.error && (
          <button onClick={revisions.retry}>Retry revision</button>
        )}
        <button onClick={() => props.onRevision(undefined)}>Open draft</button>
      </section>
    );
  return (
    <section
      className={`pl-editor pl-mobile--${mobilePanel}`}
      aria-label="Pipeline editor"
    >
      <button type="button" className="mn-back" onClick={props.onBack}>
        <ArrowLeft size={14} />
        Pipeline library
      </button>
      <div className="pl-header">
        <div>
          <h2>{base.name}</h2>
          <p className="pl-help">
            {document.definition.strategy === "adaptive_stream"
              ? "Adaptive stream"
              : "Static baseline"}{" "}
            ·{" "}
            {revision
              ? `Immutable revision ${revision.number}`
              : dirty
                ? "Unsaved draft changes"
                : "Saved draft"}
          </p>
        </div>
        <div className="pl-actions">
          <label className="pl-field">
            <span className="ex-sr-only">Design version</span>
            <select
              aria-label="Design version"
              value={revision?.id ?? "draft"}
              onChange={(event) => {
                props.onRevision(
                  event.target.value === "draft"
                    ? undefined
                    : event.target.value,
                );
                setValidation(undefined);
                review(false);
              }}
            >
              <option value="draft">Draft</option>
              {revisions.summaries.map((item) => (
                <option key={item.id} value={item.id}>
                  Revision {item.number}
                </option>
              ))}
            </select>
          </label>
          {revisions.before && (
            <button disabled={revisions.busy} onClick={() => void revisions.loadOlder()}>
              Load older revisions
            </button>
          )}
          {!readOnly && (
            <>
              <button
                type="button"
                disabled={busy || !dirty || !session.name.trim()}
                onClick={() =>
                  void action(async () => {
                    await save();
                  })
                }
              >
                <Save size={15} />
                Save draft
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    const result = await pipelinesApi.validate(
                      base.id,
                      document.definition,
                      undefined,
                      selected,
                    );
                    setValidation(result);
                    setNotice(
                      result.valid
                        ? "Graph is valid."
                        : "Graph requires changes.",
                    );
                  })
                }
              >
                <Check size={15} />
                Validate
              </button>
              <button
                type="button"
                className="mn-primary"
                disabled={busy || !session.name.trim()}
                onClick={() => void publish()}
              >
                Publish revision
              </button>
            </>
          )}
          {revision && canWrite && (
            <button
              type="button"
              className="mn-primary"
              disabled={!!props.activationBlocked && !props.activationId}
              onClick={() => review(!showActivation)}
            >
              {props.replaceService ? "Review replacement" : "Start revision"}
            </button>
          )}
        </div>
      </div>
      {!props.catalog.authoring_enabled && (
        <p className="pl-warning" role="status">
          Authoring is disabled. Saved designs and live runs remain available to
          inspect.
        </p>
      )}
      {base.archived && (
        <p className="pl-warning">This pipeline is archived.</p>
      )}
      {props.activationBlocked && (
        <p className="pl-warning" role="status">
          {props.activationBlocked}
        </p>
      )}
      {error && (
        <p className="pl-error" role="alert">
          {error}
        </p>
      )}
      {revisions.error && <p className="pl-error" role="alert">{revisions.error}</p>}
      {notice && (
        <p className="pl-notice" role="status">
          {notice}
        </p>
      )}
      {conflict && (
        <section className="pl-conflict" aria-label="Draft conflict">
          <h3>The shared design changed</h3>
          <p>
            Your local draft is preserved. Reload the shared draft or save your
            work as a separate design.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                const latest = await pipelinesApi.get(base.id);
                setSession({
                  base: latest,
                  document: { definition: latest.draft, layout: latest.layout },
                  name: latest.name,
                  description: latest.description,
                });
                setConflict(false);
                setUndo([]);
                setRedo([]);
              })
            }
          >
            Discard local changes and reload
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                const copy = await pipelinesApi.create({
                  name: `${session.name.slice(0, 110)} (copy)`,
                  description: session.description,
                  definition: session.document.definition,
                  layout: session.document.layout,
                });
                props.onOpen(copy.id);
              })
            }
          >
            Save as a new design
          </button>
        </section>
      )}
      {!readOnly && (
        <details className="pl-metadata">
          <summary>Name and description</summary>
          <label className="pl-field">
            <span>Pipeline name</span>
            <input
              maxLength={120}
              value={session.name}
              onChange={(event) =>
                setSession((previous) => ({
                  ...previous,
                  name: event.target.value,
                }))
              }
            />
          </label>
          <label className="pl-field">
            <span>Description</span>
            <textarea
              maxLength={2000}
              value={session.description}
              onChange={(event) =>
                setSession((previous) => ({
                  ...previous,
                  description: event.target.value,
                }))
              }
            />
          </label>
        </details>
      )}
      <PipelineDesignSettings
        document={document}
        readOnly={readOnly}
        onChange={commit}
      />
      <div className="pl-canvas-toolbar">
        <div className="pl-mobile-switch" aria-label="Editor panel">
          {(["graph", "components", "inspector"] as const).map((panel) => (
            <button
              type="button"
              key={panel}
              aria-pressed={mobilePanel === panel}
              onClick={() => setMobilePanel(panel)}
            >
              {panel}
            </button>
          ))}
        </div>
        {!readOnly && (
          <div className="pl-actions">
            <button
              type="button"
              disabled={!undo.length}
              aria-label="Undo graph change"
              onClick={() => {
                const next = undo[undo.length - 1]!;
                setRedo((previous) => [...previous, document]);
                setUndo((previous) => previous.slice(0, -1));
                setSession((previous) => ({ ...previous, document: next }));
                setValidation(undefined);
              }}
            >
              <Undo2 size={15} />
              Undo
            </button>
            <button
              type="button"
              disabled={!redo.length}
              aria-label="Redo graph change"
              onClick={() => {
                const next = redo[redo.length - 1]!;
                setUndo((previous) => [...previous, document]);
                setRedo((previous) => previous.slice(0, -1));
                setSession((previous) => ({ ...previous, document: next }));
                setValidation(undefined);
              }}
            >
              <Redo2 size={15} />
              Redo
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  const layout = await arrangeGraph(
                    document.definition,
                    document.layout,
                  );
                  if (currentSession.current.document !== document) {
                    setNotice(
                      "The graph changed while arranging. Arrange again to use the latest edits.",
                    );
                    return;
                  }
                  commit({ ...document, layout });
                })
              }
            >
              <LayoutGrid size={15} />
              Arrange
            </button>
          </div>
        )}
      </div>
      <div
        className={`pl-editor-grid${readOnly ? " pl-editor-grid--readonly" : ""}`}
      >
        {!readOnly && (
          <PipelineToolbox
            catalog={props.catalog}
            definition={document.definition}
            onAdd={add}
          />
        )}
        <PipelineCanvas
          document={document}
          components={props.catalog.components}
          issues={(metadata ?? validation)?.issues}
          selected={selected}
          readOnly={readOnly}
          onSelect={select}
          onChange={commit}
          onAdd={add}
          onBeginMove={() => {
            setUndo((previous) => [...previous.slice(-39), document]);
            setRedo([]);
          }}
        />
        <PipelineInspector
          document={document}
          catalog={props.catalog}
          selected={selected}
          validation={metadata ?? validation}
          readOnly={readOnly}
          onSelect={select}
          onChange={commit}
        />
      </div>
      {validation && (
        <section className="pl-validation" aria-label="Graph validation">
          <h3>
            {validation.valid ? "Valid processing graph" : "Validation errors"}
          </h3>
          {validation.issues_truncated && (
            <p className="pl-help">
              Additional validation messages were omitted to keep this report
              bounded. Resolve the listed issues, then validate again.
            </p>
          )}
          {validation.issues.length > 0 && (
            <ul>
              {validation.issues.map((issue, index) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => issue.node_id && select(issue.node_id)}
                  >
                    {issue.message}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {revision && changes.length > 0 && (
        <p className="pl-help">
          <GitBranch size={14} /> The current draft differs from this published
          revision in {changes.length} processing{" "}
          {changes.length === 1 ? "change" : "changes"}.
        </p>
      )}
      {revision &&
        showActivation &&
        (!props.activationBlocked || props.activationId) && (
          <PipelineActivation
            key={revision.id}
            revision={revision}
            previous={props.predecessor?.definition}
            replaceService={props.replaceService}
            previousBindings={
              props.predecessor
                ? Object.fromEntries(
                    (props.predecessor.run?.execution?.bindings ?? []).map(
                      (binding) => [binding.slot_id, binding.reading_id],
                    ),
                  )
                : undefined
            }
            targets={props.targets}
            services={props.services}
            byStream={props.byStream}
            initialTarget={props.initialTarget}
            initialReading={props.initialReading}
            defaultName={base.name}
            collectionReady={props.collectionReady}
            onClose={() => review(false)}
            onComplete={props.onStarted}
            operationId={props.activationId}
            onOperation={props.onOperation}
          />
        )}
      {canWrite && (
        <details className="pl-archive">
          <summary>Archive design</summary>
          <p>
            Archive hides the design from the active library. Existing revisions
            and monitoring history remain available.
            {dirty ? " Save the current draft before archiving." : ""}
          </p>
          <button
            type="button"
            disabled={busy || dirty}
            onClick={() =>
              void action(async () => {
                const saved = await pipelinesApi.metadata(base.id, {
                  expected_version: base.version,
                  name: base.name,
                  description: base.description,
                  archived: true,
                });
                setSession((previous) => ({ ...previous, base: saved }));
                setNotice("Design archived.");
              })
            }
          >
            Archive pipeline
          </button>
        </details>
      )}
      {base.archived && props.canEdit && props.catalog.authoring_enabled && (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void action(async () => {
              const saved = await pipelinesApi.metadata(base.id, {
                expected_version: base.version,
                name: base.name,
                description: base.description,
                archived: false,
              });
              setSession((previous) => ({ ...previous, base: saved }));
            })
          }
        >
          Restore pipeline
        </button>
      )}
    </section>
  );
}
