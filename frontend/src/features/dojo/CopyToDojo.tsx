import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import type { SystemStream } from "@/types/system";
import { useDojoAccess } from "./access";
import { HistoryImportDialog } from "./DatasetImport";
import "./dojo.css";

/** Copy the recorded readings of the page's device or reading into a new Dojo dataset, then open it.
 *
 * Shown only to members who may use the Dojo, and only where a numeric reading can be copied.
 */
export function CopyToDojo({ scope, readings, compact = false }: {
  /** The device, broker or reading the page is about, for the dataset's default name. */
  scope: string;
  readings: SystemStream[];
  /** An icon button for crowded headers; otherwise a labelled button. */
  compact?: boolean;
}) {
  const allowed = useDojoAccess();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (!allowed || !readings.some(item => item.value_type === "number")) return null;
  const trigger = compact
    ? <button type="button" className="ex-icon-button" aria-label="Copy to Dojo" title="Copy to Dojo"
      onClick={() => setOpen(true)}><FlaskConical size={17} /></button>
    : <Button type="button" variant="outline" onClick={() => setOpen(true)}><FlaskConical className="h-4 w-4" />Copy to Dojo</Button>;
  return <>
    {trigger}
    {open && <HistoryImportDialog open onOpenChange={setOpen} scope={scope} readings={readings}
      onCreated={dataset => navigate(`/dojo?dataset=${encodeURIComponent(dataset.id)}`)} />}
  </>;
}
