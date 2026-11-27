import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import type { BenchmarkImportResult, BenchmarkListPage, BenchmarkListQuery, CsvImportQuery, DatasetView } from "@/types/dojo.generated";
import { DOJO_LIMITS } from "@/types/dojo.generated";
import type { SystemStream } from "@/types/system";
import { dojoApi } from "./api";
import { fromLocalInput, toLocalInput } from "./model";
import { LOCALE } from "@/lib/locale";

type Layout = CsvImportQuery["layout"];
type Delimiter = NonNullable<CsvImportQuery["delimiter"]>;

function ImportDialog({ open, title, description, busy, error, submitLabel, canSubmit, onOpenChange, onSubmit, children, busyLabel = "Copying values…" }: {
  open: boolean; title: string; description: string; busy: boolean; error: string; submitLabel: string;
  canSubmit: boolean; onOpenChange: (open: boolean) => void; onSubmit: () => void; children: ReactNode; busyLabel?: string;
}) {
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) onOpenChange(next); }}>
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
            <Button type="submit" disabled={busy || !canSubmit}>{busy ? busyLabel : submitLabel}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

const stem = (name: string) => name.replace(/\.[^.]+$/, "").trim().slice(0, 120);
const megabytes = (bytes: number) => Math.round(bytes / 1024 / 1024);

/** Upload a CSV file as a new dataset. */
export function CsvImportDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (open: boolean) => void; onCreated: (dataset: DatasetView) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [layout, setLayout] = useState<Layout>("wide");
  const [timestampColumn, setTimestampColumn] = useState("");
  const [seriesColumn, setSeriesColumn] = useState("series");
  const [valueColumn, setValueColumn] = useState("value");
  const [delimiter, setDelimiter] = useState<"" | Delimiter>("");
  const [labelColumn, setLabelColumn] = useState("");
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
        ...(layout === "wide" && labelColumn.trim() ? { label_column: labelColumn.trim() } : {}),
      });
      reset(false);
      onCreated(dataset);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <ImportDialog open={open} onOpenChange={reset} title="Upload CSV" busy={busy} error={error}
    description={`Values are copied into the Dojo once; editing the file later changes nothing. At most ${
      megabytes(DOJO_LIMITS.uploadBytes)} MB, ${DOJO_LIMITS.series} series and ${DOJO_LIMITS.points.toLocaleString(LOCALE)} values.`}
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
      <label className="dj-field">Delimiter<select value={delimiter} disabled={busy}
        onChange={event => setDelimiter(event.target.value as "" | Delimiter)}>
        <option value="">Detect</option><option value=",">Comma</option><option value=";">Semicolon</option>
        <option value={"\t"}>Tab</option><option value="|">Pipe</option>
      </select></label>
    </div>
    {layout === "wide" && <label className="dj-field"><span>Label column <small>(optional)</small></span>
      <input value={labelColumn} disabled={busy} placeholder="For example: anomaly"
        onChange={event => setLabelColumn(event.target.value)} />
      <span className="dj-help">A column of 0 and 1. Each run of rows marked 1 becomes a label; the column is not stored as a series.</span>
    </label>}
    {layout === "long" && <div className="dj-field-row">
      <label className="dj-field">Series column<input required value={seriesColumn} disabled={busy}
        onChange={event => setSeriesColumn(event.target.value)} /></label>
      <label className="dj-field">Value column<input required value={valueColumn} disabled={busy}
        onChange={event => setValueColumn(event.target.value)} /></label>
    </div>}
    <p className="dj-help">Timestamps are ISO 8601 or Unix seconds or milliseconds; a time without a zone is read as UTC.</p>
  </ImportDialog>;
}

type Variant = NonNullable<BenchmarkListQuery["variant"]>;
const VARIANTS: { id: "" | Variant; label: string }[] = [
  { id: "original", label: "Original" }, { id: "distorted", label: "Distorted copies" },
  { id: "noise", label: "Noisy copies" }, { id: "", label: "All" },
];

/** Search a public benchmark collection and import series, each with its anomaly as a label. */
export function BenchmarkImportDialog({ open, onOpenChange, onImported }: {
  open: boolean; onOpenChange: (open: boolean) => void; onImported: (result: BenchmarkImportResult) => void;
}) {
  const [text, setText] = useState("");
  const [domain, setDomain] = useState("");
  const [variant, setVariant] = useState<"" | Variant>("original");
  const [page, setPage] = useState<BenchmarkListPage | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    // Typing waits a moment, so a search runs once per pause.
    const timer = window.setTimeout(() => {
      void dojoApi.benchmarks({ text: text.trim(), limit: 250, ...(domain ? { domain } : {}), ...(variant ? { variant } : {}) },
        controller.signal).then(
        next => { if (!controller.signal.aborted) { setPage(next); setError(""); } },
        reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); },
      );
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, text, domain, variant]);
  const close = (next: boolean) => {
    if (!next) { setChosen([]); setError(""); }
    onOpenChange(next);
  };
  const toggle = (id: string, on: boolean) =>
    setChosen(previous => on ? [...previous, id].slice(0, DOJO_LIMITS.benchmarkImport) : previous.filter(item => item !== id));
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const result = await dojoApi.importBenchmarks({ series_ids: chosen });
      close(false);
      onImported(result);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const collection = page?.collections[0];
  const full = chosen.length >= DOJO_LIMITS.benchmarkImport;
  return <ImportDialog open={open} onOpenChange={close} title="Add public series" busy={busy} error={error}
    busyLabel="Downloading series…"
    description="Each series becomes a dataset of its own, with its known anomaly as a label. Values are downloaded once and checked against the published file."
    submitLabel={chosen.length > 1 ? `Import ${chosen.length} series` : "Import series"} canSubmit={chosen.length > 0}
    onSubmit={() => void submit()}>
    {collection && <div className="dj-benchmark-source">
      <a href={collection.url} target="_blank" rel="noreferrer">{collection.name}</a>
      <p>{collection.description}</p>
      <p><small>By {collection.authors}. {collection.license} Cite: {collection.citation}.</small></p>
    </div>}
    <div className="dj-field-row">
      <label className="dj-field">Search<input type="search" value={text} disabled={busy} placeholder="Name or number, for example ECG or 112"
        onChange={event => setText(event.target.value)} /></label>
      <label className="dj-field">Domain<select value={domain} disabled={busy} onChange={event => setDomain(event.target.value)}>
        <option value="">All domains</option>
        {collection?.domains.map(item => <option key={item} value={item}>{item}</option>)}
      </select></label>
      <label className="dj-field">Variant<select value={variant} disabled={busy} onChange={event => setVariant(event.target.value as "" | Variant)}>
        {VARIANTS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
    </div>
    <fieldset className="dj-field"><legend>{page ? `${page.total} series` : "Series"}{chosen.length ? ` · ${chosen.length} chosen` : ""}</legend>
      {page === null ? <p className="dj-help" role="status">Loading the collection…</p>
        : page.items.length === 0 ? <p className="dj-help" role="status">No series matches.</p>
        : <ul className="dj-reading-list dj-benchmark-list">{page.items.map(item => {
          const on = chosen.includes(item.id);
          return <li key={item.id}><label>
            <input type="checkbox" checked={on} disabled={busy || (!on && full)}
              onChange={event => toggle(item.id, event.target.checked)} />
            <span><b>{String(item.number).padStart(3, "0")} · {item.name}</b>
              <small>{item.domain}{item.variant === "original" ? "" : `, ${item.variant}`} · {item.points.toLocaleString(LOCALE)} values ·
                anomaly at {item.anomaly_first.toLocaleString(LOCALE)}{item.anomaly_last > item.anomaly_first ? `–${item.anomaly_last.toLocaleString(LOCALE)}` : ""}</small></span>
            {item.dataset_id && <small>Imported</small>}
          </label></li>;
        })}</ul>}
      {full && <p className="dj-help">An import takes at most {DOJO_LIMITS.benchmarkImport} series.</p>}
    </fieldset>
  </ImportDialog>;
}

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** Windows offered for a copy; each ends now. `null` copies everything retention has kept. */
const WINDOWS = [
  { id: "all", label: "Everything stored", span: null },
  { id: "30d", label: "Last 30 days", span: 30 * DAY_MS },
  { id: "7d", label: "Last 7 days", span: 7 * DAY_MS },
  { id: "24h", label: "Last 24 hours", span: DAY_MS },
  { id: "custom", label: "Custom", span: undefined },
] as const;
type WindowId = (typeof WINDOWS)[number]["id"];

/** Copy recorded readings of the catalogue selection for one window. */
export function HistoryImportDialog({ open, onOpenChange, onCreated, scope, readings }: {
  open: boolean; onOpenChange: (open: boolean) => void; onCreated: (dataset: DatasetView) => void;
  /** What is selected in the catalogue, for the default name. */
  scope?: string;
  readings: SystemStream[];
}) {
  const numeric = useMemo(() => readings.filter(item => item.value_type === "number").slice(0, DOJO_LIMITS.series), [readings]);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [name, setName] = useState("");
  const [windowId, setWindowId] = useState<WindowId>("all");
  const [start, setStart] = useState(() => toLocalInput(Date.now() - 7 * DAY_MS));
  const [end, setEnd] = useState(() => toLocalInput(Date.now()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = chosen ?? new Set(numeric.map(item => item.id));
  const custom = windowId === "custom";
  const startAt = fromLocalInput(start), endAt = fromLocalInput(end);
  const windowValid = !custom || (!!startAt && !!endAt && endAt > startAt);
  const close = (next: boolean) => {
    if (!next) { setChosen(null); setName(""); setError(""); setWindowId("all"); }
    onOpenChange(next);
  };
  /** The window to copy, measured when the copy starts so "now" is current. */
  const copyWindow = (): { start?: string; end: string } | undefined => {
    if (custom) return startAt && endAt ? { start: startAt, end: endAt } : undefined;
    const now = Date.now();
    const span = WINDOWS.find(item => item.id === windowId)?.span ?? null;
    // A second past now keeps a value that arrives while the dialog is open.
    const until = new Date(now + 1000).toISOString();
    return span === null ? { end: until } : { start: new Date(now - span).toISOString(), end: until };
  };
  const submit = async () => {
    const chosenWindow = copyWindow();
    if (!chosenWindow) return;
    setBusy(true); setError("");
    try {
      const dataset = await dojoApi.importHistory({
        name: (name.trim() || scope || "Recorded readings").slice(0, 120),
        reading_ids: numeric.filter(item => selected.has(item.id)).map(item => item.id),
        ...chosenWindow,
      });
      close(false);
      onCreated(dataset);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <ImportDialog open={open} onOpenChange={close} title="Copy recorded readings" busy={busy} error={error}
    description="The recorded values of the chosen readings are copied into a frozen dataset. Retention and catalogue edits never change it."
    submitLabel="Copy" canSubmit={selected.size > 0 && windowValid} onSubmit={() => void submit()}>
    {numeric.length === 0
      ? <p className="dj-help" role="status">Select a device or reading with numeric values in the catalogue first.</p>
      : <fieldset className="dj-field"><legend>Readings{scope ? ` of ${scope}` : ""}</legend>
        <ul className="dj-reading-list">{numeric.map(item => <li key={item.id}><label>
          <input type="checkbox" checked={selected.has(item.id)} disabled={busy} onChange={event => {
            const next = new Set(selected);
            if (event.target.checked) next.add(item.id); else next.delete(item.id);
            setChosen(next);
          }} />{item.label}{item.unit && <small>{item.unit}</small>}</label></li>)}</ul>
      </fieldset>}
    <label className="dj-field">Name<input maxLength={120} value={name} disabled={busy} placeholder={scope ?? "Recorded readings"}
      onChange={event => setName(event.target.value)} /></label>
    <fieldset className="dj-field"><legend>Window</legend><div className="dj-choices">
      {WINDOWS.map(item => <label key={item.id}><input type="radio" name="history-window" checked={windowId === item.id}
        disabled={busy} onChange={() => setWindowId(item.id)} />{item.label}</label>)}
    </div></fieldset>
    {custom ? <>
      <div className="dj-field-row">
        <label className="dj-field">From<input type="datetime-local" step={1} value={start} disabled={busy}
          onChange={event => setStart(event.target.value)} /></label>
        <label className="dj-field">To<input type="datetime-local" step={1} value={end} disabled={busy}
          onChange={event => setEnd(event.target.value)} /></label>
      </div>
      {!windowValid && <p className="dj-error">The end must be after the start.</p>}
    </> : <p className="dj-help">{windowId === "all"
      ? "From the first value still stored up to now. Retention decides how far back that reaches."
      : "Ends now."} A dataset holds at most {DOJO_LIMITS.points.toLocaleString(LOCALE)} values; choose a shorter window if the
      copy is refused.</p>}
  </ImportDialog>;
}
