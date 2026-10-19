import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import type {
  PipelineCatalog,
  PipelineServiceView,
  PipelineView,
} from "./contracts";
import type { PipelineLayout } from "./contracts";
import { pipelinesApi } from "./api";
import { PipelineWorkbench, type InspectorPanel } from "./PipelineWorkbench";
import { PipelineDiagnostics, type PipelineState } from "./PipelineDiagnostics";
import { executableChanges, nodeOptionLabel } from "./model";
import { arrangeGraph } from "./layout";
import { useRunMetadata } from "./useRunMetadata";
import { PipelineRunHistory } from "./PipelineRunHistory";
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
  const [inspectorPanel, setInspectorPanel] = useState<InspectorPanel>(null);
  const select = (id?: string) => { setSelected(id || undefined); if (id) setInspectorPanel("component"); };
  const metadata = useRunMetadata(serviceId, selected, view?.definition);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [editing, setEditing] = useState(false);
  const [design, setDesign] = useState<PipelineView>();
  const [busy, setBusy] = useState(false);
  const [arrangement, setArrangement] = useState<{
    layout?: PipelineLayout;
    fitRequest: number;
  }>({ fitRequest: 0 });
  const { layout, fitRequest } = arrangement;
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
          setArrangement({ layout: next.layout, fitRequest: 0 });
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
      setDesign(
        view?.run?.pipeline_id
          ? await pipelinesApi.get(view.run.pipeline_id)
          : undefined,
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
                      const arranged = await arrangeGraph(
                        view.definition,
                        layout,
                      );
                      setArrangement((current) =>
                        current.layout === layout
                          ? {
                              layout: arranged,
                              fitRequest: current.fitRequest + 1,
                            }
                          : current,
                      );
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
                      setArrangement((current) => ({
                        ...current,
                        layout: saved,
                      }));
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
                    setArrangement((current) => ({
                      layout: view.layout,
                      fitRequest: current.fitRequest + 1,
                    }));
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
            <PipelineWorkbench
              document={{
                definition: view.definition,
                layout: layout ?? view.layout,
              }}
              catalog={catalog}
              validation={metadata.validation ?? view.validation ?? undefined}
              fitRequest={fitRequest}
              selected={selected}
              readOnly
              layoutEditable={arranging && !busy}
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
              onSelect={select}
              inspectorPanel={inspectorPanel}
              onInspectorPanelChange={setInspectorPanel}
              onChange={(document) => {
                if (arranging)
                  setArrangement((current) => ({
                    ...current,
                    layout: document.layout,
                  }));
              }}
              onAdd={() => {}}
            />
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
            onSelect={select}
          />
          <PipelineRunHistory
            key={serviceId}
            initial={{
              items: view.history,
              next_service_id: view.history_next_service_id,
            }}
          />
        </>
      )}
    </section>
  );
}
