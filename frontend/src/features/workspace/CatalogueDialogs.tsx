import { lazy, Suspense, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useCatalogue } from "./catalogue-context";

const StructureEditor = lazy(() => import("./SystemStructureEditor").then(module => ({ default: module.SystemStructureEditor })));

/** The catalogue editor. It also opens above the settings overlay's catalogue section. */
export function CatalogueDialogs({ toggle }: { toggle: RefObject<HTMLButtonElement | null> }) {
  const { system, document, dialog: editor, dialogOrigin, editingLocked, closeDialog } = useCatalogue();
  return <Dialog.Root open={!!editor} onOpenChange={open => { if (!open) closeDialog(); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog"
        onEscapeKeyDown={event => { if (system.saving) event.preventDefault(); }}
        onCloseAutoFocus={event => { event.preventDefault(); (dialogOrigin.current?.isConnected ? dialogOrigin.current : toggle.current)?.focus(); }}>
        <header><Dialog.Title>Edit catalogue</Dialog.Title>
          <Dialog.Close className="ex-icon-button" disabled={system.saving} aria-label="Close editor"><X size={18} /></Dialog.Close></header>
        <Dialog.Description className="ex-sr-only">Manage the saved catalogue.</Dialog.Description>
        <Suspense fallback={<p role="status">Loading…</p>}>
          {editor && <StructureEditor key={editor.key} document={document} revision={system.revision ?? 0} kind={editor.entityKind} entityId={editor.id}
            canEdit={system.canEdit && !editingLocked} saving={system.saving} saveError={system.error} onSave={system.save} onDone={closeDialog} />}
        </Suspense>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
