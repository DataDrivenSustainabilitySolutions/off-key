import { useMemo } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useDocumentTitle } from "@/hooks/use-document-title";
import type { DatasetView } from "@/types/dojo.generated";
import { useCatalogue } from "../workspace/catalogue-context";
import { DatasetDetail } from "./DatasetDetail";
import { DatasetList } from "./DatasetList";
import { useDojoAccess } from "./access";
import { datasetTab, type DatasetTab } from "./model";
import "./dojo.css";

/** The Dojo: datasets, their labels, replayed runs and comparisons, apart from live monitoring. */
export function DojoWorkspace() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { state } = useLocation();
  const allowed = useDojoAccess();
  const { selected, document } = useCatalogue();
  const datasetId = params.get("dataset");
  useDocumentTitle(!datasetId && "Dojo");
  const href = (next: Record<string, string | null>) => {
    const url = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value === null) url.delete(key); else url.set(key, value);
    }
    const query = url.toString();
    return `/dojo${query ? `?${query}` : ""}`;
  };
  const readings = useMemo(() => {
    const ids = new Set(selected?.streamIds ?? []);
    const brokers = new Map(document.connections.map(broker => [broker.id, broker.label]));
    const entities = new Map(document.devices.map(entity => [entity.id, entity.label]));
    return document.streams.filter(stream => ids.has(stream.id)).map(stream => ({
      ...stream, brokerName: brokers.get(stream.connection_id),
      entityName: stream.device_id ? entities.get(stream.device_id) : undefined,
    }));
  }, [selected, document.streams, document.connections, document.devices]);
  const open = (dataset: DatasetView) => navigate(href({ dataset: dataset.id, tab: null, run: null }), { state: { openedDataset: dataset.id } });

  return <main className="ex-main-content" aria-label="Dojo workspace">
    {!allowed ? <div className="dj-empty"><h2>The Dojo is not open to you</h2>
      <p>Ask a member who manages members for a role with the “Use the Dojo” permission.</p></div>
      : datasetId ? <DatasetDetail key={datasetId} id={datasetId} tab={datasetTab(params.get("tab"))} focusTitle={state?.openedDataset === datasetId}
        focusRun={params.get("run") ?? undefined} listHref={href({ dataset: null, tab: null, run: null })}
        onTab={(tab: DatasetTab, runId?: string) => setParams(previous => {
          const next = new URLSearchParams(previous);
          next.set("tab", tab);
          if (runId) next.set("run", runId); else next.delete("run");
          return next;
        }, { replace: true })}
        onDeleted={() => navigate(href({ dataset: null, tab: null, run: null }), { replace: true })} />
      : <DatasetList datasetHref={id => href({ dataset: id, tab: null, run: null })} onCreated={open}
        scope={selected && selected.kind !== "root" ? selected.label : undefined} readings={readings} />}
  </main>;
}
