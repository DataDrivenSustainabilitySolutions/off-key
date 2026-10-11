import { useRef, useState } from "react";
import { FileJson, Layers, Upload } from "lucide-react";
import { parseSpatialCatalog, type SpatialCatalogProjection } from "./catalog";
import type { SpatialWorkspace } from "./types";

type Props = {
  catalog?: SpatialCatalogProjection;
  active: boolean;
  workspace: SpatialWorkspace;
  onCatalog: (catalog: SpatialCatalogProjection) => void;
  onChange: (workspace: SpatialWorkspace) => void;
  onNotice: (message: string) => void;
  onOpenSaved?: () => Promise<SpatialCatalogProjection>;
};

export function SpatialCatalogImport({
  catalog,
  active,
  workspace,
  onCatalog,
  onChange,
  onNotice,
  onOpenSaved,
}: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const importFile = async (file: File) => {
    setBusy(true);
    try {
      if (file.size > 1_000_000)
        throw new Error("Catalog files must be under 1 MB.");
      const projection = parseSpatialCatalog(await file.text());
      if (!projection.summary.chargers)
        throw new Error("The catalog must contain at least one charger.");
      onCatalog(projection);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : "The catalog could not be imported.",
      );
    } finally {
      setBusy(false);
    }
  };
  const collapseAll = (collapsed: boolean) =>
    onChange({
      ...workspace,
      groups: workspace.groups.map((group) => ({ ...group, collapsed })),
    });
  const openSaved = async () => {
    if (!onOpenSaved || busy) return;
    setBusy(true);
    try {
      const projection = await onOpenSaved();
      if (!projection.summary.chargers)
        throw new Error("The saved catalog has no chargers yet.");
      onCatalog(projection);
    } catch (error) {
      onNotice(
        error instanceof Error
          ? error.message
          : "The saved catalog could not be opened.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="sp-catalog-import">
      <h3>AmbiBox catalog</h3>
      <p>
        Import the exact catalog for a local fleet preview. Broker addresses and
        credentials are excluded; collection settings are never applied.
      </p>
      <button
        className="sp-wide-button"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        <Upload size={15} />
        {busy ? "Reading catalog…" : "Import AmbiBox catalog"}
      </button>
      {onOpenSaved && (
        <button
          className="sp-wide-button"
          disabled={busy}
          onClick={() => {
            void openSaved();
          }}
        >
          <FileJson size={15} /> Open saved AmbiBox catalog
        </button>
      )}
      <input
        ref={input}
        type="file"
        hidden
        accept=".json,application/json"
        aria-label="AmbiBox catalog file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void importFile(file);
        }}
      />
      {catalog && active && (
        <>
          <div className="sp-catalog-summary">
            <FileJson size={15} />
            <span>
              {catalog.summary.brokers} brokers · {catalog.summary.chargers}{" "}
              chargers · {catalog.summary.streams} topics
            </span>
          </div>
          <div className="sp-catalog-actions">
            <button
              className="sp-wide-button"
              onClick={() => collapseAll(true)}
            >
              <Layers size={15} />
              Fleet overview
            </button>
            <button
              className="sp-wide-button"
              onClick={() => collapseAll(false)}
            >
              Expand all chargers
            </button>
          </div>
          <p>
            Expand a charger to inspect its topic definitions. Catalog structure
            is exact; live telemetry is not connected in this preview.
          </p>
        </>
      )}
    </section>
  );
}
