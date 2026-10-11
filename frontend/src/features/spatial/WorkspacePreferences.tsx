import { useRef, useState } from "react";
import {
  ArrowDownToLine,
  Crosshair,
  FolderPlus,
  RotateCcw,
  Save,
  Upload,
  X,
} from "lucide-react";
import { SpatialCatalogImport } from "./SpatialCatalogImport";
import type { SpatialCatalogProjection } from "./catalog";
import { MAX_WORKSPACE_BYTES, parseWorkspace } from "./workspace";
import type { Perspective, SpatialWorkspace } from "./types";

type SourceMode = "demo" | "hsl" | "ambibox";
type Props = {
  workspace: SpatialWorkspace;
  catalog?: SpatialCatalogProjection;
  onCatalog: (catalog: SpatialCatalogProjection) => void;
  source: SourceMode;
  sensorCount: number;
  viewName: string;
  newGroupName: string;
  onSource: (source: SourceMode) => void;
  onSensorCount: (count: number) => void;
  onViewName: (name: string) => void;
  onNewGroupName: (name: string) => void;
  onSavePerspective: () => void;
  onRestorePerspective: (perspective: Perspective) => void;
  onChange: (workspace: SpatialWorkspace) => void;
  onCreateGroup: () => void;
  onExport: () => void;
  onImport: (workspace: SpatialWorkspace) => boolean;
  onResetCamera: () => void;
  onNotice: (message: string) => void;
  namePersistenceStatus?: string;
  namePersistenceError?: string;
  onRefreshNames?: () => void;
  onOpenSavedCatalog?: () => Promise<SpatialCatalogProjection>;
  allowCatalogImport?: boolean;
};

export function WorkspacePreferences({
  workspace,
  catalog,
  onCatalog,
  source,
  sensorCount,
  viewName,
  newGroupName,
  onSource,
  onSensorCount,
  onViewName,
  onNewGroupName,
  onSavePerspective,
  onRestorePerspective,
  onChange,
  onCreateGroup,
  onExport,
  onImport,
  onResetCamera,
  onNotice,
  namePersistenceStatus,
  namePersistenceError,
  onRefreshNames,
  onOpenSavedCatalog,
  allowCatalogImport = true,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  const importLayout = async (file: File) => {
    if (file.size > MAX_WORKSPACE_BYTES) {
      onNotice(
        "View import failed: the file exceeds 1 MB. Your current view is unchanged.",
      );
      return;
    }
    setImporting(true);
    try {
      const imported = parseWorkspace(await file.text());
      if (!imported) {
        onNotice(
          "View import failed: invalid or unsupported view. Your current view is unchanged.",
        );
      } else if (onImport(imported)) {
        onNotice(
          "View imported and saved on this browser. Object positions remain automatic.",
        );
      } else {
        onNotice(
          "View import failed: browser storage is unavailable. Your current view is unchanged.",
        );
      }
    } catch {
      onNotice(
        "View import failed: the file could not be read. Your current view is unchanged.",
      );
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="sp-preferences">
      <h2>Make it yours.</h2>
      <p>
        Collections, colours, and camera position save automatically for this
        browser and user. Object positions are automatic.
      </p>
      <label>
        Data source
        <select
          aria-label="Data source"
          value={source}
          onChange={(event) => onSource(event.target.value as SourceMode)}
        >
          <option value="demo">Simulated sensor system</option>
          <option value="hsl">Live public MQTT · Helsinki</option>
          {catalog && (
            <option value="ambibox">AmbiBox · imported catalog</option>
          )}
        </select>
      </label>
      {source === "demo" && (
        <label>
          Scale experiment
          <select
            aria-label="Scale experiment"
            value={sensorCount}
            onChange={(event) => onSensorCount(Number(event.target.value))}
          >
            <option value="18">18 sensor streams</option>
            <option value="250">250 sensor streams</option>
            <option value="1000">1,000 sensor streams</option>
          </select>
        </label>
      )}
      {allowCatalogImport && (
        <SpatialCatalogImport
          catalog={catalog}
          active={source === "ambibox"}
          workspace={workspace}
          onCatalog={onCatalog}
          onChange={onChange}
          onNotice={onNotice}
          onOpenSaved={onOpenSavedCatalog}
        />
      )}
      {source === "ambibox" && namePersistenceStatus && (
        <section className="sp-name-persistence">
          <h3>Saved catalog names</h3>
          <p>
            {namePersistenceStatus} Click an object or charger title in its
            inspector to rename it.
          </p>
          {namePersistenceError && <p role="alert">{namePersistenceError}</p>}
          {onRefreshNames ? (
            <button className="sp-wide-button" onClick={onRefreshNames}>
              Refresh saved names
            </button>
          ) : (
            <a href="/login">Sign in to edit names ↗</a>
          )}
        </section>
      )}
      <section>
        <h3>Perspectives</h3>
        <p>Save a useful angle and return to it later.</p>
        <div className="sp-input-action">
          <input
            aria-label="Perspective name"
            placeholder="e.g. Energy overview"
            value={viewName}
            maxLength={40}
            onChange={(event) => onViewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSavePerspective();
            }}
          />
          <button
            aria-label="Save perspective"
            disabled={!viewName.trim()}
            onClick={onSavePerspective}
          >
            <Save size={16} />
          </button>
        </div>
        {workspace.perspectives.map((perspective) => (
          <div className="sp-perspective" key={perspective.id}>
            <button onClick={() => onRestorePerspective(perspective)}>
              <Crosshair size={14} />
              {perspective.name}
            </button>
            <button
              aria-label={`Delete ${perspective.name} perspective`}
              onClick={() =>
                onChange({
                  ...workspace,
                  perspectives: workspace.perspectives.filter(
                    (item) => item.id !== perspective.id,
                  ),
                })
              }
            >
              <X size={13} />
            </button>
          </div>
        ))}
      </section>
      <section>
        <h3>New collection</h3>
        <div className="sp-input-action">
          <input
            aria-label="New collection name"
            placeholder="Collection name"
            value={newGroupName}
            maxLength={40}
            onChange={(event) => onNewGroupName(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                newGroupName.trim() &&
                workspace.groups.length < 128
              )
                onCreateGroup();
            }}
          />
          <button
            aria-label="Add collection"
            disabled={!newGroupName.trim() || workspace.groups.length >= 128}
            onClick={onCreateGroup}
          >
            <FolderPlus size={16} />
          </button>
        </div>
        <p>
          Assign any object through its inspector. Grouping changes the view,
          never the data route.
        </p>
      </section>
      <button className="sp-wide-button" onClick={onExport}>
        <ArrowDownToLine size={15} />
        Export view
      </button>
      <button
        className="sp-wide-button"
        disabled={importing}
        onClick={() => fileInput.current?.click()}
      >
        <Upload size={15} />
        {importing ? "Importing view…" : "Import view"}
      </button>
      <input
        ref={fileInput}
        type="file"
        hidden
        accept=".json,application/json"
        aria-label="View JSON file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void importLayout(file);
        }}
      />
      <button className="sp-wide-button" onClick={onResetCamera}>
        <RotateCcw size={15} />
        Reset camera
      </button>
      <p className="sp-storage-note">
        Camera perspectives and collections stay local to this browser in the
        telemetry preview.
      </p>
      {source === "hsl" && (
        <a
          className="sp-source-credit"
          href="https://www.hsl.fi/en/opendata"
          target="_blank"
          rel="noreferrer"
        >
          © HSL {new Date().getFullYear()} · CC BY 4.0
        </a>
      )}
    </div>
  );
}
