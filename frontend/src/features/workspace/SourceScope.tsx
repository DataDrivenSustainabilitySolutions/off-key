import { X } from "lucide-react";
import { useCatalogue } from "./catalogue-context";
import { catalogueSelectionLabel } from "./catalogue-navigation";
import { navigationTrail } from "@/domain/system/navigationIndex";

export function SourceScope({ compact = false }: { compact?: boolean }) {
  const { document, index, selected, selectionMissing, selectSource } = useCatalogue();
  if (!selected && !selectionMissing) return null;
  return <div className={`workspace-source-scope${compact ? " is-compact" : ""}`} aria-label="Selected source">
    {!compact && <><small>Showing</small>
    <span title={selected ? navigationTrail(index, selected.key).slice(1).map(node => node.label).join(" / ") : undefined}>
      {catalogueSelectionLabel(document, selected) ?? "Source not found"}
    </span></>}
    <button type="button" onClick={() => selectSource(null)}>Show all sources<X size={13} aria-hidden="true" /></button>
  </div>;
}
