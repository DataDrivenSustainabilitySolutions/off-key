import { X } from "lucide-react";
import { useCatalogue } from "./catalogue-context";
import { navigationTrail } from "@/domain/system/navigationIndex";

export function SourceScope({ compact = false }: { compact?: boolean }) {
  const { document, index, selected, selectionMissing, selectSource } = useCatalogue();
  if (!selected && !selectionMissing) return null;
  const label = selected?.entityKind === "stream"
    ? document.streams.find(stream => stream.id === selected.objectId)?.label ?? selected.label
    : selected?.label ?? "Source not found";
  const parents = selected ? navigationTrail(index, selected.key).filter(node =>
    node.key !== selected.key && (node.kind === "connection" || node.kind === "device")) : [];
  return <div className={`workspace-source-scope${compact ? " is-compact" : ""}`} aria-label="Selected source">
    {!compact && <><small>Showing</small>
    <span>{[...parents.map(node => node.label), label].join(" / ")}</span></>}
    <button type="button" onClick={() => selectSource(null)}>Show all sources<X size={13} aria-hidden="true" /></button>
  </div>;
}
