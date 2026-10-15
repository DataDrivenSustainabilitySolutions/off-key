import { X } from "lucide-react";
import { useCatalogue } from "./catalogue-context";
import { navigationTrail } from "../explorer/navigationIndex";

export function SourceScope() {
  const { document, index, selected, selectionMissing, selectSource } = useCatalogue();
  if (!selected && !selectionMissing) return null;
  return <div className="workspace-source-scope" aria-label="Selected source">
    <span title={selected ? navigationTrail(index, selected.key).slice(1).map(node => node.label).join(" / ") : undefined}>
      {selected?.entityKind === "stream" ? document.streams.find(stream => stream.id === selected.objectId)?.label ?? selected.label : selected?.label ?? "Source not found"}
    </span>
    <button type="button" onClick={() => selectSource(null)}>All sources<X size={13} aria-hidden="true" /></button>
  </div>;
}
