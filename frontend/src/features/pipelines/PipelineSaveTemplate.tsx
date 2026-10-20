import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Save, X } from "lucide-react";

export function PipelineSaveTemplate({ name, description, existing, disabled, saving, error, conflict, onSave }: {
  name: string; description: string; existing: boolean; disabled: boolean; saving: boolean;
  error?: string; conflict?: boolean;
  onSave: (details: { name: string; description: string; copy?: boolean }) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(name);
  const [notes, setNotes] = useState(description);
  const save = async (copy = false) => {
    if (await onSave({ name: title.trim(), description: notes, copy })) setOpen(false);
  };
  return <Dialog.Root open={open} onOpenChange={(next) => {
    setOpen(next);
    if (next) { setTitle(name); setNotes(description); }
  }}>
    <Dialog.Trigger disabled={disabled}><Save size={15} />Save template</Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="pl-dialog-overlay" />
      <Dialog.Content className="pl-library pl-template-dialog">
        <div className="pl-component-menu-heading"><Dialog.Title>Save monitoring template</Dialog.Title>
          <Dialog.Close aria-label="Close save template"><X size={18} /></Dialog.Close>
        </div>
        <Dialog.Description className="pl-help">Reuse this processing flow with other readings. Saving a template does not start monitoring.</Dialog.Description>
        <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label className="pl-field"><span>Template name</span><input required maxLength={120} value={title}
            disabled={saving} placeholder="e.g. Equipment health" onChange={(event) => setTitle(event.target.value)} /></label>
          <label className="pl-field"><span>Description <small>(optional)</small></span><textarea maxLength={2000} value={notes}
            disabled={saving} placeholder="When to use this template" onChange={(event) => setNotes(event.target.value)} /></label>
          {error && <p className="pl-error" role="alert">{error}</p>}
          {saving && <p className="pl-help" role="status">Saving template… You can close this window and continue editing.</p>}
          {existing && <p className="pl-help">Update this template or save a separate copy. Running services keep their current configuration.</p>}
          <div className="pl-template-dialog-footer">
            <Dialog.Close type="button">{saving ? "Close" : "Cancel"}</Dialog.Close>
            {existing && <button type="button" disabled={saving || !title.trim()} onClick={() => void save(true)}>Save as new template</button>}
            <button type="submit" className="mn-primary" disabled={saving || !title.trim() || conflict}>
              {saving ? "Saving…" : existing ? "Update template" : "Save template"}</button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
