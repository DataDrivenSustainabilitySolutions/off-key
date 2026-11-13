import { X } from "lucide-react";
import { SourceIcon } from "@/components/source-icons/SourceIcon";
import { useCatalogue } from "./catalogue-context";
import { catalogueSelectionLabel } from "./catalogue-navigation";
import { navigationTrail } from "@/domain/system/navigationIndex";

export function SourceScope({ compact = false }: { compact?: boolean }) {
  const { document, index, selected, selectionMissing, selectSource } = useCatalogue();
  if (!selected && !selectionMissing) return null;
  return <div className={`workspace-source-scope${compact ? " is-compact" : ""}`} aria-label="Selected source">
    {!compact && <><small>Showing</small>
    <span className="source-identity" title={selected ? navigationTrail(index, selected.key).slice(1).map(node => node.label).join(" / ") : undefined}>
      {selected && <SourceIcon kind={selected.entityKind ?? selected.kind} appearance={selected.appearance} size={14} />}
      {catalogueSelectionLabel(document, selected) ?? "Source not found"}
    </span></>}
    <button type="button" onClick={() => selectSource(null)}>Show all sources<X size={13} aria-hidden="true" /></button>
  </div>;
}
