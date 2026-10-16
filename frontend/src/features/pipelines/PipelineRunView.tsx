import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type {
  PipelineCatalog,
  PipelineServiceView,
  PipelineView,
} from "./contracts";
import type { PipelineLayout } from "./contracts";
import { pipelinesApi } from "./api";
import PipelineCanvas from "./PipelineCanvas";
import { PipelineInspector } from "./PipelineInspector";
import { PipelineDiagnostics, type PipelineState } from "./PipelineDiagnostics";
import { executableChanges, nodeOptionLabel } from "./model";
import { arrangeGraph } from "./layout";
import { useRunMetadata } from "./useRunMetadata";
import "./pipelines.css";

export default function PipelineRunView({
  serviceId,
  displayName,
  canEdit,
  state,
  replaceable = true,
}: {
  serviceId: string;
  displayName?: string;
  canEdit: boolean;
  state?: PipelineState | null;
  replaceable?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<PipelineServiceView>();
  const [catalog, setCatalog] = useState<PipelineCatalog>();
  const [selected, setSelected] = useState<string>();
  const metadata = useRunMetadata(serviceId, selected);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [editing, setEditing] = useState(false);
  const [design, setDesign] = useState<PipelineView>();
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState<PipelineLayout>();
  const [arranging, setArranging] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      pipelinesApi.service(serviceId, controller.signal),
      pipelinesApi.catalog(controller.signal),
    ]).then(
      ([next, available]) => {
        if (!controller.signal.aborted) {
          setView(next);
          setLayout(next.layout);
          setCatalog(available);
          setError("");
        }
      },
      (reason) => {
        if (!controller.signal.aborted) setError(getErrorMessage(reason));
      },
    );
    return () => controller.abort();
  }, [serviceId, retry]);
  const open = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("pipeline", id);
    if (replaceable) next.set("replace", serviceId);
    else next.delete("replace");
    next.delete("service");
    next.delete("tab");
    setParams(next);
  };
  const prepareEdit = async () => {
    setBusy(true);
    setError("");
    try {
      const designs = await pipelinesApi.list();
      setDesign(
        designs.find((item) =>
          item.revisions.some(
            (revision) => revision.id === view?.run?.revision_id,
          ),
        ),
      );
      setEditing(true);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="pl-run" aria-label="Running pipeline">
      {error && (
        <p className="pl-error" role="alert">
          {error}
          <button onClick={() => setRetry((value) => value + 1)}>Retry</button>
        </p>
      )}
      {!view || !catalog ? (
        <p role="status">Loading execution graph…</p>
      ) : (
        <>
          <div className="pl-header">
            <div>
              <h3>
                {view.legacy
                  ? "Existing monitoring configuration"
                  : "Execution revision"}
              </h3>
              <p className="pl-help">
                {view.legacy
                  ? "Derived from the saved launch configuration."
                  : `Run ${view.run?.id ?? "unavailable"} · ${view.run?.status ?? "unknown"}`}{" "}
                · this graph is immutable.
              </p>
            </div>
            {canEdit && catalog.authoring_enabled && (
              <div className="pl-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void prepareEdit()}
                >
                  Edit design
                </button>
                {view.run && !arranging && (
                  <button type="button" onClick={() => setArranging(true)}>
                    Adjust arrangement
                  </button>
                )}
              </div>
            )}
          </div>
          {arranging && layout && (
            <div className="pl-canvas-toolbar">
              <p className="pl-help">
                Arrangement is presentation only. Learning and processing
                continue.
              </p>
              <div className="pl-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      setLayout(await arrangeGraph(view.definition, layout));
                    } catch (reason) {
                      setError(getErrorMessage(reason));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Arrange automatically
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const saved = await pipelinesApi.saveLayout(
                        serviceId,
                        layout,
                      );
                      setLayout(saved);
                      setView({ ...view, layout: saved });
                      setArranging(false);
                      setError("");
                    } catch (reason) {
                      setError(getErrorMessage(reason));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Save arrangement
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setLayout(view.layout);
                    setArranging(false);
                  }}
                >
                  Discard arrangement
                </button>
              </div>
            </div>
          )}
          {editing && (
            <section className="pl-conflict" aria-label="Choose pipeline draft">
              <h4>Edit a reusable design</h4>
              {design ? (
                <>
                  <p>
                    The shared draft for “{design.name}” may differ from this
                    run. Opening it keeps the running revision active.
                  </p>
                  <p>
                    {
                      executableChanges(
                        view.definition,
                        design.draft,
                        catalog.components,
                      ).length
                    }{" "}
                    processing changes compared with this run.
                  </p>
                  <button type="button" onClick={() => open(design.id)}>
                    Open shared draft
                  </button>
                </>
              ) : (
                <p>
                  Save this configuration as a reusable design before editing.
                </p>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const copy = await pipelinesApi.create({
                      name: `${(displayName ?? "Monitoring").slice(0, 100)} pipeline`,
                      description: "",
                      definition: view.definition,
                      layout: view.layout,
                    });
                    open(copy.id);
                  } catch (reason) {
                    setError(getErrorMessage(reason));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save as a new design
              </button>
              <button type="button" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </section>
          )}
          <div className="pl-editor-grid pl-editor-grid--readonly">
            <PipelineCanvas
              document={{
                definition: view.definition,
                layout: layout ?? view.layout,
              }}
              components={catalog.components}
              selected={selected}
              readOnly
              layoutEditable={arranging}
              states={
                state && state.run_id === view.run?.id
                  ? Object.fromEntries(
                      Object.entries(state.nodes).map(([id, node]) => [
                        id,
                        node.state,
                      ]),
                    )
                  : undefined
              }
              onSelect={setSelected}
              onChange={(document) => {
                if (arranging) setLayout(document.layout);
              }}
              onAdd={() => {}}
            />
            <PipelineInspector
              document={{ definition: view.definition, layout: view.layout }}
              catalog={catalog}
              selected={selected}
              validation={metadata.validation ?? view.validation ?? undefined}
              readOnly
              onSelect={setSelected}
              onChange={() => {}}
            />
          </div>
          {metadata.error && (
            <p role="status" className="pl-warning">
              Component metadata could not refresh. {metadata.error}
              <button type="button" onClick={metadata.retry}>
                Retry component metadata
              </button>
            </p>
          )}
          {(metadata.validation ?? view.validation)?.issues
            .filter((issue) => issue.code === "metadata_budget")
            .map((issue) => (
              <p key={issue.code} className="pl-help">
                {issue.message} Configured selections remain visible in their
                saved order.
              </p>
            ))}
          <PipelineDiagnostics
            state={state}
            selected={selected}
            expectedRunId={view.run?.id}
            nodeLabels={Object.fromEntries(
              view.definition.nodes.map((node) => [
                node.id,
                nodeOptionLabel(
                  node,
                  { definition: view.definition, layout: view.layout },
                  catalog.components,
                ),
              ]),
            )}
            onSelect={setSelected}
          />
          <details className="pl-history">
            <summary>Linked monitoring history ({view.history.length})</summary>
            <ul>
              {view.history.map((run) => (
                <li key={run.id}>
                  <Link
                    to={`/?service=${encodeURIComponent(run.service_id)}&tab=pipeline`}
                  >
                    {run.id}
                  </Link>{" "}
                  · {run.status} · {run.created_at}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}
