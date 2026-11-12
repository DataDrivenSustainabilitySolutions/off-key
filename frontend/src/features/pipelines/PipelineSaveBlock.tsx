import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineBlockCreate } from "@/types/pipelines.generated";
import type { PipelineComponent } from "./contracts";
import { blockChain, blockSteps } from "./blocks";
import { nodeOptionLabeler, type GraphDocument } from "./model";

const listed = (names: string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/** Name the steps from one step on and keep them in the library as a block. */
export function PipelineSaveBlock({ document, components, from, onSave, onClose }: {
  document: GraphDocument;
  components: PipelineComponent[];
  /** The step the block starts at. */
  from: string;
  onSave: (request: PipelineBlockCreate) => Promise<void>;
  onClose: () => void;
}) {
  const chain = blockChain(document.definition, from);
  const label = nodeOptionLabeler(document, components);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [through, setThrough] = useState(chain.length - 1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const steps = chain.slice(0, through + 1);
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await onSave({ name: name.trim(), description, steps: blockSteps(document, steps) });
      onClose();
    } catch (reason) {
      setError(getErrorMessage(reason));
      setSaving(false);
    }
  };
  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Portal><Dialog.Overlay className="pl-dialog-overlay" />
      <Dialog.Content className="pl-library pl-template-dialog">
        <div className="pl-component-menu-heading"><Dialog.Title>Save as block</Dialog.Title>
          <Dialog.Close aria-label="Close save block"><X size={18} /></Dialog.Close>
        </div>
        <Dialog.Description className="pl-help">Keep steps with their settings to add them to any service. This design stays as it is.</Dialog.Description>
        <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label className="pl-field"><span>Block name</span><input required maxLength={120} value={name}
            disabled={saving} placeholder="e.g. Scale and reduce" onChange={(event) => setName(event.target.value)} /></label>
          <label className="pl-field"><span>Description <small>(optional)</small></span><textarea maxLength={2000} value={description}
            disabled={saving} placeholder="When to use this block" onChange={(event) => setDescription(event.target.value)} /></label>
          {chain.length > 1 && <label className="pl-field"><span>Last step</span>
            <select value={through} disabled={saving} onChange={(event) => setThrough(Number(event.target.value))}>
              {chain.map((node, index) => <option key={node.id} value={index}>{label(node)}</option>)}
            </select></label>}
          <p className="pl-help">The block holds {steps.length === 1 ? "1 step" : `${steps.length} steps`}: {listed(steps.map(label))}.</p>
          {error && <p className="pl-error" role="alert">{error}</p>}
          <div className="pl-template-dialog-footer">
            <Dialog.Close type="button">Cancel</Dialog.Close>
            <button type="submit" className="mn-primary" disabled={saving || !name.trim()}>{saving ? "Saving…" : "Save block"}</button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
