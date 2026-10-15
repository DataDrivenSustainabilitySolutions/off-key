import { useId, useRef, useState } from "react";
import { Box, ChevronDown, Database, Download, Layers, LoaderCircle, LockKeyhole, Plus, Radio, Server, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { importSystemDocument, MAX_SYSTEM_BYTES } from "@/features/catalogue/systemDocument";
import type { SystemDocument, SystemEntityKind } from "@/features/catalogue/systemTypes";
import { CatalogueImportReview } from "./CatalogueImportReview";

type Props = {
  document: SystemDocument;
  revision: number;
  canEdit: boolean;
  saving: boolean;
  error: string;
  onImport: (document: SystemDocument, revision: number) => Promise<boolean>;
  onExport: () => Promise<void>;
  onCreate: (kind: SystemEntityKind) => void;
  onEdit?: (kind: SystemEntityKind, id: string) => void;
};
type Candidate = { document: SystemDocument; revision: number; fileName: string };
const itemCount = (count: number, singular: string) =>
  count.toLocaleString() + " " + (count === 1 ? singular : singular === "entity" ? "entities" : singular + "s");
const catalogueSummary = (document: SystemDocument, includeGroups = false) => [
  itemCount(document.connections.length, "broker"),
  itemCount(document.devices.length, "entity"),
  itemCount(document.streams.length, "reading"),
  ...(includeGroups ? [itemCount(document.groups.length, "catalogue group")] : []),
].join(" · ");
const creationActions = [
  { kind: "connection", label: "Add broker", description: "Connect an MQTT server", icon: Server },
  { kind: "device", label: "Add entity", description: "Describe a device or asset", icon: Box },
  { kind: "stream", label: "Add reading", description: "Register a value from a topic", icon: Radio },
  { kind: "group", label: "Add catalogue group", description: "Organise related sources", icon: Layers },
] as const;

export function ExplorerSettings({
  document, revision, canEdit, saving, error, onImport, onExport, onCreate, onEdit,
}: Props) {
  const entitySelectId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const fileSequence = useRef(0);
  const [candidate, setCandidate] = useState<Candidate>();
  const [fileError, setFileError] = useState("");
  const [pending, setPending] = useState<"read" | "import" | "export">();
  const disabled = saving || pending !== undefined;
  const failureMessage = (failure: unknown) =>
    failure instanceof SyntaxError ? "Use a valid JSON catalogue file." : getErrorMessage(failure).slice(0, 240);

  const readFile = async (file: File) => {
    if (!canEdit || disabled || busy.current) return;
    const sequence = ++fileSequence.current;
    const selectedRevision = revision;
    busy.current = true;
    setPending("read");
    setCandidate(undefined);
    setFileError("");
    try {
      if (file.size > MAX_SYSTEM_BYTES) throw new Error("Use a catalogue file smaller than 1 MiB.");
      const imported = importSystemDocument(await file.text());
      if (sequence === fileSequence.current)
        setCandidate({ document: imported, revision: selectedRevision, fileName: file.name });
    } catch (failure) {
      if (sequence === fileSequence.current) setFileError(failureMessage(failure));
    } finally {
      busy.current = false;
      setPending(undefined);
    }
  };

  const importCandidate = async () => {
    if (!candidate || !canEdit || disabled || busy.current) return;
    busy.current = true;
    setPending("import");
    setFileError("");
    try {
      if (await onImport(candidate.document, candidate.revision)) setCandidate(undefined);
      else setFileError("The catalogue was not imported. Refresh and review the saved version.");
    } catch (failure) {
      setFileError(failureMessage(failure));
    } finally {
      busy.current = false;
      setPending(undefined);
    }
  };

  const exportFile = async () => {
    if (disabled || busy.current) return;
    busy.current = true;
    setPending("export");
    setFileError("");
    try {
      await onExport();
    } catch (failure) {
      setFileError(failureMessage(failure));
    } finally {
      busy.current = false;
      setPending(undefined);
    }
  };

  return (
    <div className="catalogue-settings">
      <div className="catalogue-settings-content">
        <div className="catalogue-settings-overview" aria-label="Current catalogue">
          <Database size={20} aria-hidden="true" />
          <div>
            <span className="catalogue-settings-eyebrow">Current catalogue</span>
            <strong>{document.label}</strong>
            <p>{catalogueSummary(document)}</p>
          </div>
        </div>
        {!canEdit && <p className="catalogue-settings-access"><LockKeyhole size={15} aria-hidden="true" />Editing is currently unavailable. You can still export the catalogue.</p>}

        <section className="catalogue-settings-section" aria-label="Manage sources">
          <div className="catalogue-settings-section-heading">
            <h3>Manage sources</h3>
            <p>{onEdit ? "Add to your catalogue or update an existing entity." : "Add connections, entities and readings to your catalogue."}</p>
          </div>
          <div className="catalogue-settings-create-grid">
            {creationActions.map(({ kind, label, description, icon: Icon }) => (
              <button key={kind} type="button" className="catalogue-settings-create" aria-label={label}
                disabled={!canEdit || disabled || (kind === "stream" && !document.connections.length)} onClick={() => onCreate(kind)}>
                <span className="catalogue-settings-action-icon"><Icon size={18} aria-hidden="true" /></span>
                <span className="catalogue-settings-action-copy"><strong>{label}</strong><span>{description}</span></span>
                <Plus size={14} className="catalogue-settings-action-plus" aria-hidden="true" />
              </button>
            ))}
          </div>
          {!document.connections.length && <p className="catalogue-settings-hint">Add a broker before registering readings.</p>}
          {onEdit && document.devices.length > 0 && <div className="catalogue-settings-entity">
            <label htmlFor={entitySelectId}>Edit an existing entity</label>
            <div className="catalogue-settings-select">
              <select id={entitySelectId} aria-label="Edit entity" value="" disabled={!canEdit || disabled}
                onChange={event => { if (event.target.value) onEdit("device", event.target.value); }}>
                <option value="">Choose an entity to edit…</option>
                {document.devices.map(entity => <option key={entity.id} value={entity.id}>{entity.label}</option>)}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>
          </div>}
        </section>

        <section className="catalogue-settings-section catalogue-settings-files" aria-label="Import and export">
          <div className="catalogue-settings-section-heading">
            <h3>Import &amp; export</h3>
            <p>Keep a copy of your setup or bring in another catalogue.</p>
          </div>
          <div className="catalogue-settings-file-actions">
            <div className="catalogue-settings-file-row">
              <Download size={19} aria-hidden="true" />
              <div className="catalogue-settings-action-copy"><strong>Export a copy</strong><span>Download your current catalogue as JSON.</span></div>
              <Button type="button" variant="outline" disabled={disabled} onClick={() => void exportFile()}>Export catalogue</Button>
            </div>
            <div className="catalogue-settings-file-row">
              <Upload size={19} aria-hidden="true" />
              <div className="catalogue-settings-action-copy"><strong>Import a catalogue</strong><span>Review a JSON file before replacing this catalogue.</span></div>
              <Button type="button" variant="outline" disabled={!canEdit || disabled} onClick={() => fileInput.current?.click()}>Import file</Button>
            </div>
          </div>
          <p className="catalogue-settings-hint">JSON files up to 1 MiB. Importing replaces the current catalogue.</p>
          <input ref={fileInput} type="file" hidden disabled={!canEdit || disabled} accept=".json,application/json" aria-label="Catalogue file"
            onChange={event => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void readFile(file);
            }} />

          {candidate && <CatalogueImportReview name={candidate.document.label} fileName={candidate.fileName}
            summary={catalogueSummary(candidate.document, true)} disabled={disabled} canEdit={canEdit} importing={pending === "import"}
            onConfirm={() => void importCandidate()} onCancel={() => {
              fileSequence.current += 1;
              setCandidate(undefined);
              setFileError("");
            }} />}
          {pending && <p className="catalogue-settings-status" role="status"><LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
            {pending === "read" ? "Reading your file…" : pending === "import" ? "Saving catalogue…" : "Preparing your export…"}</p>}
          {(fileError || error) && <p className="catalogue-settings-error" role="alert">{fileError || error}</p>}
        </section>
      </div>
      <footer className="catalogue-settings-footer"><span>Shared across your workspace</span><span>Revision {revision}</span></footer>
    </div>
  );
}

export default ExplorerSettings;
