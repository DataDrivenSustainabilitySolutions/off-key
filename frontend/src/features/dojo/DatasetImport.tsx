import { useId, useMemo, useState, type FormEvent, type ReactElement, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import type { CsvImportQuery, DatasetView } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { getLocalTimeZone } from "../charts/telemetry-chart";
import { dojoApi } from "./api";
import { fromLocalInput, toLocalInput } from "./model";

type Layout = CsvImportQuery["layout"];
type Delimiter = NonNullable<CsvImportQuery["delimiter"]>;

function ImportDialog({ open, trigger, title, description, busy, error, submitLabel, canSubmit, onOpenChange, onSubmit, children }: {
  open: boolean; title: string; description: string; busy: boolean; error: string; submitLabel: string;
  trigger: ReactElement; canSubmit: boolean; onOpenChange: (open: boolean) => void; onSubmit: () => void; children: ReactNode;
}) {
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) onOpenChange(next); }}>
    <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog" onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
        onPointerDownOutside={event => { if (busy) event.preventDefault(); }}>
        <Dialog.Title>{title}</Dialog.Title>
        <Dialog.Description className="dj-help">{description}</Dialog.Description>
        <form onSubmit={(event: FormEvent) => { event.preventDefault(); if (canSubmit && !busy) onSubmit(); }}>
          {children}
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !canSubmit}>{busy ? "Copying values…" : submitLabel}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

const stem = (name: string) => name.replace(/\.[^.]+$/, "").trim().slice(0, 120);
const megabytes = (bytes: number) => Math.round(bytes / 1024 / 1024);

/** Upload a CSV file as a new dataset. */
export function CsvImportDialog({ open, trigger, onOpenChange, onCreated }: {
  open: boolean; trigger: ReactElement; onOpenChange: (open: boolean) => void; onCreated: (dataset: DatasetView) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [layout, setLayout] = useState<Layout>("wide");
  const [timestampColumn, setTimestampColumn] = useState("");
  const [seriesColumn, setSeriesColumn] = useState("series");
  const [valueColumn, setValueColumn] = useState("value");
  const [delimiter, setDelimiter] = useState<"" | Delimiter>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const tooLarge = !!file && file.size > DOJO_LIMITS.uploadBytes;
  const reset = (next: boolean) => {
    if (!next) { setFile(null); setName(""); setError(""); }
    onOpenChange(next);
  };
  const submit = async () => {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const dataset = await dojoApi.importCsv(file, {
        name: name.trim(), filename: file.name, layout,
        ...(timestampColumn.trim() ? { timestamp_column: timestampColumn.trim() } : {}),
        ...(layout === "long" ? { series_column: seriesColumn.trim(), value_column: valueColumn.trim() } : {}),
        ...(delimiter ? { delimiter } : {}),
      });
      reset(false);
      onCreated(dataset);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <ImportDialog open={open} trigger={trigger} onOpenChange={reset} title="Upload CSV" busy={busy} error={error}
    description={`Values are copied into the Dojo once; editing the file later changes nothing. At most ${
      megabytes(DOJO_LIMITS.uploadBytes)} MB, ${DOJO_LIMITS.series} series and ${DOJO_LIMITS.points.toLocaleString()} values.`}
    submitLabel="Upload" canSubmit={!!file && !tooLarge && !!name.trim()} onSubmit={() => void submit()}>
    <label className="dj-field">File
      <input type="file" accept=".csv,.tsv,.txt,text/csv" disabled={busy} onChange={event => {
        const next = event.target.files?.[0] ?? null;
        setFile(next);
        if (next && !name.trim()) setName(stem(next.name));
      }} />
      {tooLarge && <span className="dj-error">The file is {megabytes(file.size)} MB; upload at most {megabytes(DOJO_LIMITS.uploadBytes)} MB.</span>}
    </label>
    <label className="dj-field">Name<input required maxLength={120} value={name} disabled={busy}
      onChange={event => setName(event.target.value)} /></label>
    <fieldset className="dj-field"><legend>Layout</legend><div className="dj-choices">
      <label><input type="radio" name="layout" checked={layout === "wide"} disabled={busy} onChange={() => setLayout("wide")} />
        One column per series</label>
      <label><input type="radio" name="layout" checked={layout === "long"} disabled={busy} onChange={() => setLayout("long")} />
        One row per value</label>
    </div></fieldset>
    <div className="dj-field-row">
      <label className="dj-field"><span>Timestamp column <small>(optional)</small></span><input value={timestampColumn} disabled={busy}
        placeholder={layout === "wide" ? "First column" : "timestamp"} onChange={event => setTimestampColumn(event.target.value)} /></label>
      <label className="dj-field">Delimiter<select aria-label="Delimiter" value={delimiter} disabled={busy}
        onChange={event => setDelimiter(event.target.value as "" | Delimiter)}>
        <option value="">Detect</option><option value=",">Comma</option><option value=";">Semicolon</option>
        <option value={"\t"}>Tab</option><option value="|">Pipe</option>
      </select></label>
    </div>
    {layout === "long" && <div className="dj-field-row">
      <label className="dj-field">Series column<input required value={seriesColumn} disabled={busy}
        onChange={event => setSeriesColumn(event.target.value)} /></label>
      <label className="dj-field">Value column<input required value={valueColumn} disabled={busy}
        onChange={event => setValueColumn(event.target.value)} /></label>
    </div>}
    <p className="dj-help">Timestamps are ISO 8601 or Unix seconds or milliseconds; a time without a zone is read as UTC.</p>
  </ImportDialog>;
}

const DAY_MS = 86_400_000;
const READING_PAGE_SIZE = 24;
export type HistoryReading = SystemStream & { brokerName?: string; entityName?: string };

function HistoryReadingPicker({ readings, scope, selected, pickedCount, busy, onChange }: {
  readings: HistoryReading[];
  scope?: string;
  selected: Set<string>;
  pickedCount: number;
  busy: boolean;
  onChange: (id: string, checked: boolean) => void;
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const large = readings.length > DOJO_LIMITS.series;
  const query = filter.trim().toLocaleLowerCase();
  const matches = useMemo(() => readings.filter(item =>
    [item.label, item.entityName, item.brokerName, item.topic].some(value => value?.toLocaleLowerCase().includes(query))),
  [readings, query]);
  const lastPage = Math.max(0, Math.ceil(matches.length / READING_PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const offset = currentPage * READING_PAGE_SIZE;
  const visible = large ? matches.slice(offset, offset + READING_PAGE_SIZE) : readings;
  return <fieldset className="dj-field"><legend>Readings{scope ? ` of ${scope}` : ""}</legend>
    {large && <>
      <p className="dj-help" role="status">{pickedCount} selected. Choose up to {DOJO_LIMITS.series} of {readings.length.toLocaleString()} readings.</p>
      <label className="dj-field">Find a reading
        <input type="search" value={filter} disabled={busy} onChange={event => { setFilter(event.target.value); setPage(0); }} />
      </label>
    </>}
    {visible.length ? <ul className="dj-reading-list">{visible.map(item => {
      const checked = selected.has(item.id);
      return <li key={item.id}><label>
        <input type="checkbox" checked={checked} disabled={busy || !checked && pickedCount >= DOJO_LIMITS.series}
          onChange={event => onChange(item.id, event.target.checked)} /><span>
          {item.label}{item.unit && ` (${item.unit})`}
          {item.entityName && <span className="dj-reading-entity">{item.entityName}</span>}
          <small>{[item.brokerName, item.topic].filter(Boolean).join(" · ")}</small>
        </span>
      </label></li>;
    })}</ul> : <p className="dj-help">No readings match your search.</p>}
    {large && lastPage > 0 && <div className="dj-reading-pages">
      <Button variant="outline" size="sm" disabled={busy || currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</Button>
      <span role="status">{offset + 1}–{Math.min(offset + READING_PAGE_SIZE, matches.length)} of {matches.length.toLocaleString()}</span>
      <Button variant="outline" size="sm" disabled={busy || currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</Button>
    </div>}
  </fieldset>;
}

/** Copy recorded readings of the catalogue selection for one window. */
export function HistoryImportDialog({ open, trigger, onOpenChange, onCreated, onChooseSource, scope, readings }: {
  open: boolean; trigger: ReactElement; onOpenChange: (open: boolean) => void; onCreated: (dataset: DatasetView) => void;
  onChooseSource?: () => void;
  /** What is selected in the catalogue, for the default name. */
  scope?: string;
  readings: HistoryReading[];
}) {
  const numeric = useMemo(() => readings.filter(item => item.value_type === "number"), [readings]);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [name, setName] = useState("");
  const [start, setStart] = useState(() => toLocalInput(Date.now() - 7 * DAY_MS));
  const [end, setEnd] = useState(() => toLocalInput(Date.now()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timeZoneHint = useId();
  const selected = chosen ?? new Set(numeric.length <= DOJO_LIMITS.series ? numeric.map(item => item.id) : []);
  const picked = numeric.filter(item => selected.has(item.id));
  const single = numeric.length === 1 ? numeric[0] : undefined;
  const defaultName = single?.entityName ? `${single.entityName} · ${single.label}` : scope || "Recorded readings";
  const startAt = fromLocalInput(start), endAt = fromLocalInput(end);
  const windowValid = !!startAt && !!endAt && endAt > startAt;
  const close = (next: boolean) => {
    if (!next) { setChosen(null); setName(""); setError(""); }
    onOpenChange(next);
  };
  const submit = async () => {
    if (!startAt || !endAt) return;
    setBusy(true); setError("");
    try {
      const dataset = await dojoApi.importHistory({
        name: (name.trim() || defaultName).slice(0, 120),
        reading_ids: picked.map(item => item.id),
        start: startAt, end: endAt,
      });
      close(false);
      onCreated(dataset);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const needsSource = numeric.length === 0;
  return <ImportDialog open={open} trigger={trigger} onOpenChange={close} title="Copy recorded readings" busy={busy} error={error}
    description="The recorded values of the chosen readings are copied into a frozen dataset. Retention and catalogue edits never change it."
    submitLabel={needsSource && onChooseSource ? "Choose a reading" : "Copy"}
    canSubmit={needsSource ? !!onChooseSource : picked.length > 0 && windowValid}
    onSubmit={needsSource && onChooseSource ? onChooseSource : () => void submit()}>
    {needsSource ? <p className="ex-banner">Choose a numeric reading or its entity in the catalogue.</p> : <>
      <HistoryReadingPicker readings={numeric} scope={scope} selected={selected} pickedCount={picked.length} busy={busy}
        onChange={(id, checked) => {
          const next = new Set(selected);
          if (checked) next.add(id); else next.delete(id);
          setChosen(next);
        }} />
      <label className="dj-field">Name<input maxLength={120} value={name} disabled={busy} placeholder={defaultName}
        onChange={event => setName(event.target.value)} /></label>
      <div className="dj-field-row">
        <label className="dj-field">From<input type="datetime-local" step={1} value={start} disabled={busy} aria-describedby={timeZoneHint}
          onChange={event => setStart(event.target.value)} /></label>
        <label className="dj-field">To<input type="datetime-local" step={1} value={end} disabled={busy} aria-describedby={timeZoneHint}
          onChange={event => setEnd(event.target.value)} /></label>
      </div>
      <p className="dj-help" id={timeZoneHint}>Times use {getLocalTimeZone()}.</p>
      {!windowValid && <p className="dj-error">The end must be after the start.</p>}
    </>}
  </ImportDialog>;
}
