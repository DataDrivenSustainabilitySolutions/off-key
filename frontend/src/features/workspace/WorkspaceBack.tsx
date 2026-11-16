import { ArrowLeft } from "lucide-react";
import { useCatalogue } from "./catalogue-context";

/**
 * The way back from a selected source to the whole tab. Every tab that turns into a source page
 * puts it in the same place, so the page does not move when you switch tabs.
 */
export function WorkspaceBack({ label }: { label: string }) {
  const { selectSource } = useCatalogue();
  return <button type="button" className="ex-workspace-back" onClick={() => selectSource(null)}>
    <ArrowLeft size={14} aria-hidden="true" />{label}
  </button>;
}
