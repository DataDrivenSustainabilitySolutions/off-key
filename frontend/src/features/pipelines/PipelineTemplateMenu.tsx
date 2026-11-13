import { useEffect, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Copy, X } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineCatalog } from "./contracts";
import { hasFittedDetector } from "./learning";
import type { GraphDocument } from "./model";
import { pipelinesApi } from "./api";
import { arrangeGraph } from "./layout";
import { PipelineDesignBrowser } from "./PipelineDesignBrowser";

export function PipelineTemplateMenu({
  catalog, disabled, onBuiltIn, onLoad, onOpenFile, onManage, onLoading,
}: {
  catalog: PipelineCatalog;
  disabled: boolean;
  onBuiltIn: (id: string) => void;
  onLoad: (document: GraphDocument, name: string, description: string) => void;
  /** A design saved as a file, chosen from the device. */
  onOpenFile: (file: File) => void;
  onManage: () => void;
  onLoading: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
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
      const definition = design.draft;
      const placed = definition.nodes.every((node) => design.layout.nodes[node.id]);
      const layout = placed
        ? { ...design.layout, nodes: Object.fromEntries(definition.nodes.map((node) => [node.id, design.layout.nodes[node.id]!])) }
        : await arrangeGraph(definition, design.layout);
      if (controller.signal.aborted) return;
      onLoad({ definition, layout }, design.name, design.description);
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
    <Popover.Trigger disabled={disabled || busy}><Copy size={15} />Load template</Popover.Trigger>
    <Popover.Portal><Popover.Content className="pl-library pl-template-popover" align="end" sideOffset={8} collisionPadding={16}
      aria-label="Monitoring templates" onInteractOutside={(event) => { if (busy) event.preventDefault(); }}
      onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }}>
      <div className="pl-header"><h3>Load a template</h3>
        <Popover.Close disabled={busy} aria-label="Close templates"><X size={15} /></Popover.Close>
      </div>
      <p className="pl-help">Use a starting flow or a saved template. Changes here leave the original untouched.</p>
      <div className="pl-starting-points" aria-label="Starting flows">
        {catalog.templates.map((template) => <button key={template.id} type="button" disabled={busy}
          aria-label={`Use ${template.name}`} onClick={() => { onBuiltIn(template.id); setOpen(false); }}>
          <strong>{template.name}</strong><span>{hasFittedDetector(template.definition, catalog.components)
            ? "Fits and freezes preprocessing on a baseline" : "Learns incrementally from the stream"}</span>
        </button>)}
      </div>
      <h4>Your templates</h4>
      <PipelineDesignBrowser selecting disabled={busy} onSelect={(id) => void load(id)} />
      {busy && <p role="status">Loading template…</p>}
      {error && <p className="pl-error" role="alert">{error}</p>}
      <div className="pl-template-footer">
        <button type="button" disabled={busy} onClick={() => { setOpen(false); onManage(); }}>Manage templates</button>
        <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}>Open a file…</button>
        <input ref={fileInput} type="file" hidden accept=".json,application/json" aria-label="Design file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            // The same file can be chosen again after it was changed.
            event.target.value = "";
            if (!file) return;
            setOpen(false);
            onOpenFile(file);
          }} />
      </div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}
