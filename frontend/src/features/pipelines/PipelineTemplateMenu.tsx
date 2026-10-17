import { useEffect, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Copy, X } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineCatalog } from "./contracts";
import type { GraphDocument } from "./model";
import { pipelinesApi } from "./api";
import { PipelineDesignBrowser } from "./PipelineDesignBrowser";

export function PipelineTemplateMenu({
  catalog, disabled, onBuiltIn, onLoad, onManage, onLoading,
}: {
  catalog: PipelineCatalog;
  disabled: boolean;
  onBuiltIn: (id: string) => void;
  onLoad: (document: GraphDocument, name: string, description: string, version: string) => void;
  onManage: () => void;
  onLoading: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const load = async (id: string) => {
    if (disabled || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    onLoading(true);
    setError("");
    try {
      const design = await pipelinesApi.get(id, controller.signal);
      if (design.archived) throw new Error("This design has been archived. Choose another saved design.");
      const latest = design.revisions.reduce<(typeof design.revisions)[number] | undefined>(
        (selected, revision) => !selected || revision.number > selected.number ? revision : selected, undefined,
      );
      const revision = latest ? await pipelinesApi.revision(id, latest.id, controller.signal) : undefined;
      if (controller.signal.aborted) return;
      onLoad({ definition: revision?.definition ?? design.draft, layout: design.layout },
        design.name, design.description, revision ? `Revision ${revision.number}` : `Saved draft · version ${design.version}`);
      setOpen(false);
    } catch (reason) {
      if (!controller.signal.aborted) setError(getErrorMessage(reason));
    } finally {
      if (!controller.signal.aborted) {
        pending.current = null;
        setBusy(false);
        onLoading(false);
      }
    }
  };
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <Popover.Trigger disabled={disabled || busy}><Copy size={15} />Templates</Popover.Trigger>
    <Popover.Portal><Popover.Content className="pl-library pl-template-popover" align="end" sideOffset={8}
      aria-label="Monitoring templates" onInteractOutside={(event) => { if (busy) event.preventDefault(); }}
      onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }}>
      <div className="pl-header"><h3>Start from a template</h3>
        <Popover.Close disabled={busy} aria-label="Close templates"><X size={15} /></Popover.Close>
      </div>
      <p className="pl-help">Load a starting flow or a saved design, then edit your own copy. Undo restores the previous flow.</p>
      <div className="pl-starting-points" aria-label="Starting flows">
        {catalog.templates.map((template) => <button key={template.id} type="button" disabled={busy}
          aria-label={`Use ${template.name}`} onClick={() => { onBuiltIn(template.id); setOpen(false); }}>
          <strong>{template.name}</strong><span>{template.definition.strategy === "adaptive_stream"
            ? "Learns incrementally from the stream" : "Fits and freezes preprocessing on a baseline"}</span>
        </button>)}
      </div>
      <h4>Saved designs</h4>
      <p className="pl-help">Published designs use their latest revision. Unpublished designs use their saved draft.</p>
      <PipelineDesignBrowser selecting disabled={busy} onSelect={(id) => void load(id)} />
      {busy && <p role="status">Loading template…</p>}
      {error && <p className="pl-error" role="alert">{error}</p>}
      <button type="button" className="pl-manage-designs" disabled={busy} onClick={onManage}>Manage saved designs</button>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}
