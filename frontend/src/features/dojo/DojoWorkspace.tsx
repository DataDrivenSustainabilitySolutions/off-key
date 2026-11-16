import { useMemo } from "react";
import { Activity, X } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { SourceIcon } from "@/components/source-icons/SourceIcon";
import { useDocumentTitle } from "@/hooks/use-document-title";
import type { DatasetView } from "@/types/dojo.generated";
import { useCatalogue } from "../workspace/catalogue-context";
import { catalogueSelectionLabel, withCatalogueSource } from "../workspace/catalogue-navigation";
import { detailsHref, selectedSource } from "../workspace/reporting-scope";
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
  const { selected, document, selectSource, streamIds } = useCatalogue();
  const datasetId = params.get("dataset");
  useDocumentTitle(!allowed ? "Access denied" : datasetId ? "Dataset" : "Datasets", "Dojo");
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
  // Choosing a source in the catalogue keeps the Dojo open: it picks what “Copy recorded
  // readings” starts from. Its readings page stays one link away.
  const scoped = selected && selected.kind !== "root" ? selected : undefined;
  // The same readings page Reporting links to, when the selection belongs to one device or broker.
  const source = scoped && selectedSource(streamIds, document);
  const scopeLabel = scoped && (catalogueSelectionLabel(document, scoped) ?? scoped.label);
  const selection = scoped && <div className="dj-scope" aria-label="Selected source">
    <small>Selected</small>
    <span className="dj-scope-source"><span className="source-identity" title={scopeLabel}>
      <SourceIcon kind={scoped.entityKind ?? scoped.kind} appearance={scoped.appearance} size={14} />{scopeLabel}</span>
    <button type="button" className="dj-scope-clear" aria-label="Clear selection" title="Clear selection" onClick={() => selectSource(null)}>
      <X size={14} aria-hidden="true" /></button></span>
    {source && <Link className="dj-scope-link" to={withCatalogueSource(detailsHref(source), scoped)}>
      <Activity size={14} aria-hidden="true" />{source.kind === "device" ? "Device readings" : "Broker readings"}</Link>}
  </div>;
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
        scope={scoped?.label} readings={readings} selection={selection} />}
  </main>;
}
