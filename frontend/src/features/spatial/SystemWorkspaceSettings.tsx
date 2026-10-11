import { useRef, useState } from "react";
import { Download, Plus, RefreshCw, Upload } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import { InlineName } from "./InlineName";
import {
  importSystemDocument,
  MAX_SYSTEM_BYTES,
  validateSystemDocument,
} from "./systemDocument";
import { parseWorkspace } from "./workspace";
import type { SystemDocument, SystemEntityKind } from "./systemTypes";
import type { SpatialWorkspace } from "./types";
type Props = {
  document: SystemDocument;
  revision: number;
  workspace: SpatialWorkspace;
  view?: "isometric" | "top";
  canEdit: boolean;
  saving: boolean;
  saveError: string;
  onSave: (document: SystemDocument, revision?: number) => Promise<boolean>;
  onLayout: (workspace: SpatialWorkspace) => void;
  onCreate: (kind: SystemEntityKind) => void;
  onExport: (layout: boolean) => Promise<void>;
  onImport: (
    document: SystemDocument,
    layout?: SpatialWorkspace,
    expectedRevision?: number,
  ) => Promise<boolean>;
  onRefresh: () => void;
  onNotice: (notice: string) => void;
  onPreview?: (source: "demo" | "hsl") => void;
  onView?: (view: "isometric" | "top") => void;
};
export function SystemWorkspaceSettings({
  document,
  revision,
  workspace,
  view = "isometric",
  canEdit,
  saving,
  saveError,
  onSave,
  onLayout,
  onCreate,
  onExport,
  onImport,
  onRefresh,
  onNotice,
  onPreview,
  onView,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [candidate, setCandidate] = useState<{
    document: SystemDocument;
    layout?: SpatialWorkspace;
    revision: number;
  }>();
  const [fileError, setFileError] = useState("");
  const [perspectiveName, setPerspectiveName] = useState("");
  const [policyEdit, setPolicyEdit] = useState<{
    baseline: SystemDocument;
    revision: number;
    policy: SystemDocument["default_policy"];
  } | null>(null);
  const policy = policyEdit?.policy ?? document.default_policy;
  const [policyError, setPolicyError] = useState("");
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const fileSequence = useRef(0);
  const disabled = saving || pending;
  const updatePolicy = (fields: Partial<SystemDocument["default_policy"]>) => {
    setPolicyError("");
    setPolicyEdit((current) => ({
      baseline: current?.baseline ?? document,
      revision: current?.revision ?? revision,
      policy: { ...(current?.policy ?? document.default_policy), ...fields },
    }));
  };
  const savePolicy = async () => {
    if (!policyEdit || busy.current || disabled || !canEdit) return;
    busy.current = true;
    setPending(true);
    setPolicyError("");
    try {
      const next = validateSystemDocument({
        ...policyEdit.baseline,
        default_policy: policyEdit.policy,
      });
      if (await onSave(next, policyEdit.revision)) {
        setPolicyEdit(null);
        onNotice("Default policy saved.");
      } else
        setPolicyError(
          "Policy was not saved. Refresh and review the current definition.",
        );
    } catch (failure) {
      setPolicyError(getErrorMessage(failure));
    } finally {
      busy.current = false;
      setPending(false);
    }
  };
  const importCandidate = async () => {
    if (!candidate || busy.current || disabled || !canEdit) return;
    busy.current = true;
    setPending(true);
    setFileError("");
    try {
      if (
        await onImport(candidate.document, candidate.layout, candidate.revision)
      )
        setCandidate(undefined);
      else
        setFileError(
          "The configuration was not imported. Refresh and review the saved definition.",
        );
    } catch (failure) {
      setFileError(getErrorMessage(failure));
    } finally {
      busy.current = false;
      setPending(false);
    }
  };
  const exportFile = async (layout: boolean) => {
    if (busy.current || disabled) return;
    busy.current = true;
    setPending(true);
    setFileError("");
    try {
      await onExport(layout);
    } catch (failure) {
      setFileError(getErrorMessage(failure));
    } finally {
      busy.current = false;
      setPending(false);
    }
  };
  const readFile = async (file: File) => {
    const sequence = ++fileSequence.current;
    const expectedRevision = revision;
    setCandidate(undefined);
    setFileError("");
    try {
      if (file.size > MAX_SYSTEM_BYTES * 2)
        throw new Error("Use a configuration file smaller than 2 MiB.");
      const contents = await file.text();
      const raw = JSON.parse(contents);
      if (raw?.format === "aberration-workspace") {
        if (raw.schema_version !== 1)
          throw new Error("Unsupported workspace version.");
        const layout = parseWorkspace(JSON.stringify(raw.layout));
        if (!layout) throw new Error("The workspace layout is invalid.");
        const imported = importSystemDocument(JSON.stringify(raw.system));
        if (sequence === fileSequence.current)
          setCandidate({
            document: imported,
            layout,
            revision: expectedRevision,
          });
      } else {
        const imported = importSystemDocument(contents);
        if (sequence === fileSequence.current)
          setCandidate({ document: imported, revision: expectedRevision });
      }
    } catch (failure) {
      if (sequence === fileSequence.current)
        setFileError(getErrorMessage(failure));
    }
  };
  const savePerspective = () => {
    const name = perspectiveName.trim();
    if (!name) return;
    onLayout({
      ...workspace,
      perspectives: [
        ...workspace.perspectives,
        {
          id: `perspective:${crypto.randomUUID()}`,
          name,
          camera: structuredClone(workspace.camera),
          view,
        },
      ].slice(-12),
    });
    setPerspectiveName("");
    onNotice("Perspective saved on this browser.");
  };
  return (
    <div className="sp-inspector-content sp-system-settings">
      <span className="sp-overline">Saved system</span>
      <h2>
        <InlineName
          value={document.label}
          editable={canEdit}
          ariaLabel="Rename system"
          saveError={saveError}
          onSave={async (label) => {
            if (!(await onSave({ ...document, label }, revision)))
              throw new Error("Name was not saved.");
          }}
        />
      </h2>
      <p className="sp-system-intro">
        Configuration saves to the database. Camera, personal groups, and
        perspectives save on this browser and travel with a workspace export.
      </p>
      <section>
        <h3>Build your structure</h3>
        <div className="sp-system-add-grid">
          {(["connection", "device", "stream", "group"] as const).map(
            (kind) => (
              <button
                key={kind}
                aria-label={`Add ${kind}`}
                disabled={
                  !canEdit ||
                  disabled ||
                  (kind === "stream" && !document.connections.length)
                }
                onClick={() => onCreate(kind)}
              >
                <Plus size={13} />
                {kind}
              </button>
            ),
          )}
        </div>
      </section>
      <section>
        <h3>Configuration files</h3>
        <button
          className="sp-wide-button"
          disabled={disabled}
          onClick={() => void exportFile(false)}
        >
          <Download size={14} />
          Export configuration
        </button>
        <button
          className="sp-wide-button"
          disabled={disabled}
          onClick={() => void exportFile(true)}
        >
          <Download size={14} />
          Export workspace
        </button>
        <button
          className="sp-wide-button"
          disabled={!canEdit || disabled}
          onClick={() => fileInput.current?.click()}
        >
          <Upload size={14} />
          Import configuration
        </button>
        <input
          ref={fileInput}
          hidden
          disabled={!canEdit || disabled}
          type="file"
          accept=".json,application/json"
          aria-label="System configuration file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void readFile(file);
          }}
        />
        <small>
          Workspace files include the configuration and saved view preferences.
          Credentials are referenced, never embedded.
        </small>
        {fileError && (
          <p role="alert" className="sp-inline-name-error">
            {fileError}
          </p>
        )}
        {candidate && (
          <div className="sp-system-import-preview">
            <strong>{candidate.document.label}</strong>
            <p>
              {candidate.document.connections.length} connections ·{" "}
              {candidate.document.devices.length} devices ·{" "}
              {candidate.document.streams.length} streams
            </p>
            <p>
              This replaces the saved definition
              {candidate.layout ? " and restores its view preferences" : ""}.
              Connect to view live data.
            </p>
            <button
              className="sp-system-primary"
              disabled={disabled || !canEdit}
              onClick={() => void importCandidate()}
            >
              Replace saved definition
            </button>
            <button
              disabled={disabled}
              onClick={() => {
                fileSequence.current += 1;
                setCandidate(undefined);
              }}
            >
              Cancel import
            </button>
          </div>
        )}
      </section>
      <section>
        <h3>Default collection policy</h3>
        <p>
          Streams can override this setting. Saving a policy does not activate a
          connection.
        </p>
        <label>
          Mode
          <select
            aria-label="Default policy"
            disabled={!canEdit || disabled}
            value={policy.mode}
            onChange={(event) =>
              updatePolicy({ mode: event.target.value as typeof policy.mode })
            }
          >
            <option value="off">Off</option>
            <option value="sample">Sample</option>
            <option value="original">Original rate</option>
          </select>
        </label>
        {policy.mode === "sample" && (
          <label>
            Sampling interval (seconds)
            <input
              aria-label="Default sampling interval"
              disabled={!canEdit || disabled}
              type="number"
              min={1}
              max={3600}
              value={policy.interval_seconds}
              onChange={(event) =>
                updatePolicy({ interval_seconds: Number(event.target.value) })
              }
            />
          </label>
        )}
        <button
          className="sp-wide-button"
          disabled={
            !canEdit ||
            disabled ||
            !policyEdit ||
            JSON.stringify(policy) ===
              JSON.stringify(policyEdit.baseline.default_policy)
          }
          onClick={() => void savePolicy()}
        >
          Save default policy
        </button>
        {policyError && <p role="alert">{policyError}</p>}
      </section>
      <section>
        <h3>Perspectives</h3>
        <div className="sp-input-action">
          <input
            aria-label="Perspective name"
            placeholder="e.g. System overview"
            maxLength={40}
            value={perspectiveName}
            onChange={(event) => setPerspectiveName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") savePerspective();
            }}
          />
          <button
            aria-label="Save perspective"
            disabled={!perspectiveName.trim()}
            onClick={savePerspective}
          >
            <Plus size={14} />
          </button>
        </div>
        {workspace.perspectives.map((perspective) => (
          <div className="sp-perspective" key={perspective.id}>
            <button
              onClick={() => {
                onLayout({
                  ...workspace,
                  camera: structuredClone(perspective.camera),
                });
                onView?.(perspective.view ?? "isometric");
              }}
            >
              {perspective.name}
            </button>
            <button
              aria-label={`Delete ${perspective.name} perspective`}
              onClick={() =>
                onLayout({
                  ...workspace,
                  perspectives: workspace.perspectives.filter(
                    (item) => item.id !== perspective.id,
                  ),
                })
              }
            >
              ×
            </button>
          </div>
        ))}
      </section>
      {onPreview && (
        <section>
          <h3>Telemetry previews</h3>
          <button className="sp-wide-button" onClick={() => onPreview("demo")}>
            Explore simulated telemetry
          </button>
          <button className="sp-wide-button" onClick={() => onPreview("hsl")}>
            Explore public MQTT
          </button>
        </section>
      )}
      <button
        className="sp-wide-button"
        disabled={disabled}
        onClick={onRefresh}
      >
        <RefreshCw size={14} />
        Refresh saved system
      </button>
      <small>
        Database revision {revision}. Existing live collection is managed
        separately.
      </small>
      {saveError && (
        <p className="sp-inline-name-error" role="alert">
          {saveError}
        </p>
      )}
    </div>
  );
}
