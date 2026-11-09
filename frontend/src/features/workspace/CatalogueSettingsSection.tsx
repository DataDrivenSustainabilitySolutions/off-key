import { useState } from "react";
import { serializeSystemDocument } from "@/domain/system/systemDocument";
import ExplorerSettings from "./ExplorerSettings";
import { useCatalogue } from "./catalogue-context";
import "./catalogue-settings.css";

/** Sources, import and export for the shared catalogue, shown in the settings overlay. */
export default function CatalogueSettingsSection() {
  const { system, document, editingLocked, openEditor, collapseAll, showCollection, selectSource, positions } = useCatalogue();
  const [notice, setNotice] = useState("");
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
  return <div className="app-settings-catalogue">
    <ExplorerSettings document={document} revision={system.revision ?? 0} canEdit={system.canEdit && !editingLocked}
      saving={system.saving} error={system.error} onExport={exportCatalogue} onCreate={openEditor} onEdit={openEditor}
      onImport={async (next, revision) => {
        setNotice("");
        if (editingLocked || !await system.save(next, revision)) return false;
        collapseAll(); showCollection(null); positions.clear(); selectSource(null);
        setNotice("Catalogue imported and saved.");
        return true;
      }} />
    {notice && <p role="status" className="catalogue-settings-feedback">{notice}</p>}
  </div>;
}
