import { lazy, Suspense, useState, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { serializeSystemDocument } from "../catalogue/systemDocument";
import { CatalogueSettingsHeader } from "../explorer/CatalogueSettingsHeader";
import { useCatalogue } from "./catalogue-context";

const Settings = lazy(() => import("../explorer/ExplorerSettings"));
const StructureEditor = lazy(() => import("../catalogue/SystemStructureEditor").then(module => ({ default: module.SystemStructureEditor })));

export function CatalogueDialogs({ toggle }: { toggle: RefObject<HTMLButtonElement | null> }) {
  const { system, document, index, dialog, dialogOrigin, editingLocked, openEditor, closeDialog, browse, selectSource, positions } = useCatalogue();
  const editor = dialog?.kind === "editor" ? dialog : undefined;
  const [notice, setNotice] = useState("");
  const dismiss = () => { if (!system.saving) { setNotice(""); closeDialog(); } };
  const exportCatalogue = async () => {
    setNotice("");
    const saved = await system.refresh();
    if (!saved) throw new Error("The saved catalogue could not be read. Try again.");
    const url = URL.createObjectURL(new Blob([serializeSystemDocument(saved)], { type: "application/json" }));
    const link = window.document.createElement("a");
    link.href = url; link.download = "aberration-system.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Saved catalogue exported.");
  };
  return <Dialog.Root open={!!dialog} onOpenChange={open => { if (!open) dismiss(); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className={`ex-dialog${editor ? "" : " ex-settings-dialog"}`}
        onEscapeKeyDown={event => { if (system.saving) event.preventDefault(); }}
        onCloseAutoFocus={event => { event.preventDefault(); (dialogOrigin.current?.isConnected ? dialogOrigin.current : toggle.current)?.focus(); }}>
        {editor ? <><header><Dialog.Title>Edit catalogue</Dialog.Title>
          <Dialog.Close className="ex-icon-button" disabled={system.saving} aria-label="Close settings"><X size={18} /></Dialog.Close></header>
          <Dialog.Description className="ex-sr-only">Manage the saved catalogue.</Dialog.Description></>
          : <CatalogueSettingsHeader disabled={system.saving} />}
        <Suspense fallback={<p role="status">Loading…</p>}>
          {editor ? <StructureEditor key={editor.key} document={document} revision={system.revision ?? 0} kind={editor.entityKind} entityId={editor.id}
            canEdit={system.canEdit && !editingLocked} saving={system.saving} saveError={system.error} onSave={system.save} onDone={dismiss} />
            : <Settings document={document} revision={system.revision ?? 0} canEdit={system.canEdit && !editingLocked}
              saving={system.saving} error={system.error} onExport={exportCatalogue} onCreate={openEditor} onEdit={openEditor}
              onImport={async (next, revision) => {
                setNotice("");
                if (editingLocked || !await system.save(next, revision)) return false;
                browse(index.rootKey); positions.clear(); selectSource(null);
                setNotice("Catalogue imported and saved.");
                return true;
              }} />}
        </Suspense>
        {!editor && notice && <p role="status" className="catalogue-settings-feedback">{notice}</p>}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
