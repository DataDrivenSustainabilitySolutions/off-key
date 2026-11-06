import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
    return document.readings.filter(stream => ids.has(stream.id));
  }, [selected, document.readings]);
  const open = (dataset: DatasetView) => navigate(href({ dataset: dataset.id, tab: null }));

  return <main className="ex-main-content" aria-label="Dojo workspace">
    {!allowed ? <div className="dj-empty"><h2>The Dojo is not open to you</h2>
      <p>Ask a member who manages members for a role with the “Use the Dojo” permission.</p></div>
      : datasetId ? <DatasetDetail key={datasetId} id={datasetId} tab={datasetTab(params.get("tab"))}
        listHref={href({ dataset: null, tab: null })}
        onTab={(tab: DatasetTab) => setParams(previous => { const next = new URLSearchParams(previous); next.set("tab", tab); return next; },
          { replace: true })}
        onDeleted={() => navigate(href({ dataset: null, tab: null }), { replace: true })} />
      : <DatasetList datasetHref={id => href({ dataset: id, tab: null })} onCreated={open}
        scope={selected && selected.kind !== "root" ? selected.label : undefined} readings={readings} />}
  </main>;
}
