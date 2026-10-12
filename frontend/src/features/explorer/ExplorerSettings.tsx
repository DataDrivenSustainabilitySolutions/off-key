import { useRef, useState } from "react";
import { Download, Plus, Upload } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import {
  importSystemDocument,
  MAX_SYSTEM_BYTES,
} from "@/features/catalogue/systemDocument";
import type { SystemDocument, SystemEntityKind } from "@/features/catalogue/systemTypes";

type Props = {
  document: SystemDocument;
  revision: number;
  canEdit: boolean;
  saving: boolean;
  error: string;
  onImport: (document: SystemDocument, revision: number) => Promise<boolean>;
  onExport: () => Promise<void>;
  onCreate: (kind: SystemEntityKind) => void;
};
type Candidate = { document: SystemDocument; revision: number };
const itemCount = (count: number, singular: string) =>
  `${count.toLocaleString()} ${count === 1 ? singular : singular === "entity" ? "entities" : `${singular}s`}`;

export function ExplorerSettings({
  document, revision, canEdit, saving, error, onImport, onExport, onCreate,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const fileSequence = useRef(0);
  const [candidate, setCandidate] = useState<Candidate>();
  const [fileError, setFileError] = useState("");
  const [pending, setPending] = useState<"read" | "import" | "export">();
  const disabled = saving || pending !== undefined;

  const failureMessage = (failure: unknown) =>
    failure instanceof SyntaxError
      ? "Use a valid JSON catalogue file."
      : getErrorMessage(failure).slice(0, 240);

  const readFile = async (file: File) => {
    if (!canEdit || disabled || busy.current) return;
    const sequence = ++fileSequence.current;
    const selectedRevision = revision;
    busy.current = true;
    setPending("read");
    setCandidate(undefined);
    setFileError("");
    try {
      if (file.size > MAX_SYSTEM_BYTES)
        throw new Error("Use a catalogue file smaller than 1 MiB.");
      const contents = await file.text();
      const imported = importSystemDocument(contents);
      if (sequence === fileSequence.current)
        setCandidate({ document: imported, revision: selectedRevision });
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
      if (await onImport(candidate.document, candidate.revision))
        setCandidate(undefined);
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
    <div className="ex-settings">
      <section className="ex-settings-section">
        <h3>Catalogue structure</h3>
        <p>{document.label}</p>
        <div className="ex-settings-actions">
          {([
            ["connection", "broker"], ["device", "entity"],
            ["stream", "reading"], ["group", "catalogue group"],
          ] as const).map(([kind, label]) => (
            <button
              key={kind}
              type="button"
              disabled={!canEdit || disabled || (kind === "stream" && !document.connections.length)}
              onClick={() => onCreate(kind)}
            ><Plus size={14} aria-hidden="true" />Add {label}</button>
          ))}
        </div>
      </section>

      <section className="ex-settings-section">
        <h3>Catalogue files</h3>
        <p>Export or restore your catalogue structure.</p>
        <div className="ex-settings-actions">
          <button type="button" disabled={disabled} onClick={() => void exportFile()}>
            <Download size={14} aria-hidden="true" />Export catalogue
          </button>
          <button type="button" disabled={!canEdit || disabled} onClick={() => fileInput.current?.click()}>
            <Upload size={14} aria-hidden="true" />Import file
          </button>
        </div>
        <input
          ref={fileInput}
          type="file"
          hidden
          disabled={!canEdit || disabled}
          accept=".json,application/json"
          aria-label="Catalogue file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void readFile(file);
          }}
        />

        {candidate && (
          <div className="ex-settings-import" aria-label="Import preview">
            <strong>{candidate.document.label}</strong>
            <p>
              {itemCount(candidate.document.connections.length, "broker")} ·{" "}
              {itemCount(candidate.document.devices.length, "entity")} ·{" "}
              {itemCount(candidate.document.streams.length, "reading")} ·{" "}
              {itemCount(candidate.document.groups.length, "catalogue group")}
            </p>
            <p>
              This replaces the saved catalogue. Live listening starts separately.
            </p>
            <div className="ex-settings-actions">
              <button
                className="ex-settings-primary"
                type="button"
                disabled={!canEdit || disabled}
                onClick={() => void importCandidate()}
              >Replace saved catalogue</button>
              <button type="button" disabled={disabled} onClick={() => {
                fileSequence.current += 1;
                setCandidate(undefined);
                setFileError("");
              }}>Cancel import</button>
            </div>
          </div>
        )}
        {pending && <p role="status">{pending === "read" ? "Reading your file…" : pending === "import" ? "Saving catalogue…" : "Preparing your export…"}</p>}
        {(fileError || error) && <p className="ex-settings-error" role="alert">{fileError || error}</p>}
      </section>
      <small>Saved catalogue revision {revision}.</small>
    </div>
  );
}

export default ExplorerSettings;
