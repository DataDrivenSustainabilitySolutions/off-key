import { Activity, X } from "lucide-react";
import { Link } from "react-router-dom";
import { SourceIcon } from "@/components/source-icons/SourceIcon";
import { useCatalogue } from "./catalogue-context";
import { catalogueSelectionLabel, withCatalogueSource } from "./catalogue-navigation";
import { detailsHref, selectedSource } from "./reporting-scope";

/**
 * The catalogue selection on a tab that keeps its own page, such as Reporting or the Dojo: the
 * source, a way to clear it and, when it belongs to one device or broker, its readings page.
 * Every such tab shows it the same way, under its heading.
 */
export function SelectedSourceBar({ disabled = false }: { disabled?: boolean }) {
  const { document, selected, selectionMissing, selectSource, streamIds } = useCatalogue();
  const scoped = selected && selected.kind !== "root" ? selected : undefined;
  if (!scoped && !selectionMissing) return null;
  const label = scoped ? catalogueSelectionLabel(document, scoped) ?? scoped.label : "Source not found";
  const source = scoped && selectedSource(streamIds, document);
  return <div className="ex-selected-source" role="group" aria-label="Selected source">
    <small>Selected</small>
    <span className="ex-selected-source-name"><span className="source-identity" title={label}>
      {scoped && <SourceIcon kind={scoped.entityKind ?? scoped.kind} appearance={scoped.appearance} size={14} />}{label}</span>
    <button type="button" className="ex-selected-source-clear" aria-label="Show all sources" title="Show all sources"
      disabled={disabled} onClick={() => selectSource(null)}><X size={14} aria-hidden="true" /></button></span>
    {source && <Link className="ex-selected-source-link" to={withCatalogueSource(detailsHref(source), scoped)}>
      <Activity size={14} aria-hidden="true" />{source.kind === "device" ? "Device readings" : "Broker readings"}</Link>}
  </div>;
}
