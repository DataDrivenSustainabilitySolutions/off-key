import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { DOJO_LIMITS, type DatasetSummary, type DatasetView, type FaultSuiteCreate, type StudyView, type SuiteView } from "@/types/dojo.generated";
import { pipelinesApi } from "../pipelines/api";
import type { PipelineDefinition } from "../pipelines/contracts";
import { dojoApi } from "./api";
import { sharedSeriesNames } from "./suites";

/** Choose datasets, in order, for a suite that never changes once made. */
export function SuiteCreateDialog({ open, datasets, onOpenChange, onCreated }: {
  open: boolean; datasets: DatasetSummary[]; onOpenChange: (open: boolean) => void; onCreated: (suite: SuiteView) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const close = (next: boolean) => {
    if (!next) { setName(""); setDescription(""); setChosen([]); setError(""); }
    onOpenChange(next);
  };
  const toggle = (id: string, on: boolean) =>
    setChosen(previous => on ? [...previous, id] : previous.filter(item => item !== id));
  const full = chosen.length >= DOJO_LIMITS.suiteDatasets;
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const suite = await dojoApi.createSuite({ name: name.trim(), description: description.trim(), dataset_ids: chosen });
      close(false);
      onCreated(suite);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) close(next); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog">
        <Dialog.Title>New benchmark suite</Dialog.Title>
        <Dialog.Description className="dj-help">A suite is a fixed set of labelled datasets. Every study runs one design over
          all of them, so studies of the same suite can be ranked and compared fairly. Its datasets cannot change later.</Dialog.Description>
        <form onSubmit={event => { event.preventDefault(); if (name.trim() && chosen.length && !busy) void submit(); }}>
          <label className="dj-field">Name<input required maxLength={120} value={name} disabled={busy}
            onChange={event => setName(event.target.value)} /></label>
          <label className="dj-field">Description <small>(optional)</small><textarea maxLength={2000} value={description}
            disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
          <fieldset className="dj-field"><legend>Datasets ({chosen.length} of at most {DOJO_LIMITS.suiteDatasets})</legend>
            <div className="dj-choices dj-suite-choices">{datasets.map(item => {
              const checked = chosen.includes(item.id);
              return <label key={item.id} className="dj-check"><input type="checkbox" checked={checked}
                disabled={busy || (!checked && full)} onChange={event => toggle(item.id, event.target.checked)} />
                {item.name}<small>{item.series_count} series</small></label>;
            })}</div>
            {datasets.length === 0 && <span className="dj-help">Add datasets first.</span>}
          </fieldset>
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => close(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !name.trim() || chosen.length === 0}>{busy ? "Creating…" : "Create suite"}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

type Choice = { key: string; name: string; group: "template" | "design"; definition?: PipelineDefinition };
const AUTOMATIC = "";

/** Run one design over every dataset of a suite, binding inputs to series by name. */
export function StudyCreateDialog({ open, suite, onOpenChange, onCreated }: {
  open: boolean; suite: SuiteView; onOpenChange: (open: boolean) => void; onCreated: (study: StudyView) => void;
}) {
  const [choices, setChoices] = useState<Choice[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [key, setKey] = useState("");
  const [definition, setDefinition] = useState<PipelineDefinition | null>(null);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selection = useRef<AbortController | null>(null);
  const names = useMemo(() => sharedSeriesNames(suite.items), [suite.items]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void Promise.all([pipelinesApi.catalog(controller.signal), pipelinesApi.list({ limit: 100 }, controller.signal)])
      .then(([catalog, library]) => {
        if (controller.signal.aborted) return;
        setChoices([
          ...catalog.templates.map(item => ({ key: `template:${item.id}`, name: item.name, group: "template" as const,
            definition: item.definition })),
          ...library.items.map(item => ({ key: `design:${item.id}`, name: item.name, group: "design" as const })),
        ]);
      })
      .catch(reason => { if (!controller.signal.aborted) setLoadError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [open]);

  const choose = async (next: string) => {
    selection.current?.abort();
    const controller = new AbortController();
    selection.current = controller;
    setKey(next); setDefinition(null); setError("");
    const choice = choices?.find(item => item.key === next);
    if (!choice) return;
    try {
      const chosen = choice.definition ?? (await pipelinesApi.get(next.slice("design:".length), controller.signal)).draft;
      if (controller.signal.aborted) return;
      setDefinition(chosen);
      setBindings({});
      setName(choice.name);
    } catch (reason) {
      if (!controller.signal.aborted) setError(getErrorMessage(reason));
    }
  };
  const close = (next: boolean) => {
    if (!next) { selection.current?.abort(); setKey(""); setDefinition(null); setError(""); setLoadError(""); }
    onOpenChange(next);
  };
  const slots = definition?.input_slots ?? [];
  const submit = async () => {
    if (!definition) return;
    setBusy(true); setError("");
    try {
      const study = await dojoApi.createStudy({ suite_id: suite.id, name: name.trim(), definition,
        bindings: Object.fromEntries(Object.entries(bindings).filter(([, value]) => value !== AUTOMATIC)) });
      close(false);
      onCreated(study);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const templates = choices?.filter(item => item.group === "template") ?? [];
  const designs = choices?.filter(item => item.group === "design") ?? [];
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) close(next); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog">
        <Dialog.Title>New study</Dialog.Title>
        <Dialog.Description className="dj-help">Queues one run of the design on each of the suite's {suite.items.length} datasets.
          Single runs go first, and the study waits its turn as one place in the queue.</Dialog.Description>
        <form onSubmit={event => { event.preventDefault(); if (definition && !busy) void submit(); }}>
          {loadError && <p className="dj-error" role="alert">{loadError}</p>}
          <label className="dj-field">Design
            <select value={key} disabled={busy || !choices} onChange={event => void choose(event.target.value)}>
              <option value="" disabled>{choices ? "Choose a template or design" : "Loading designs…"}</option>
              {templates.length > 0 && <optgroup label="Templates">{templates.map(item =>
                <option key={item.key} value={item.key}>{item.name}</option>)}</optgroup>}
              {designs.length > 0 && <optgroup label="Your designs">{designs.map(item =>
                <option key={item.key} value={item.key}>{item.name}</option>)}</optgroup>}
            </select>
          </label>
          {definition && <>
            <fieldset className="dj-field"><legend>Inputs</legend>
              <p className="dj-help">Each input reads the series of that name in every dataset. Left automatic, a one-input
                design reads a dataset's only series, and an input reads the series named like it.</p>
              <div className="dj-bindings">{slots.map(slot => <label key={slot.id} className="dj-binding">
                <span>{slot.label}{slot.unit ? ` (${slot.unit})` : ""}</span>
                <select value={bindings[slot.id] ?? AUTOMATIC} disabled={busy} aria-label={`Series for ${slot.label}`}
                  onChange={event => setBindings(previous => ({ ...previous, [slot.id]: event.target.value }))}>
                  <option value={AUTOMATIC}>Automatic</option>
                  {names.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>)}</div>
            </fieldset>
            <label className="dj-field">Study name<input maxLength={120} value={name} disabled={busy}
              onChange={event => setName(event.target.value)} /></label>
          </>}
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => close(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !definition}>{busy ? "Queueing…" : "Start study"}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

type FaultKind = NonNullable<FaultSuiteCreate["kinds"]>[number];
const FAULT_KINDS: { id: FaultKind; label: string }[] = [
  { id: "step", label: "Step" }, { id: "drift", label: "Drift" }, { id: "gain", label: "Gain error" },
  { id: "noise", label: "Rising noise" }, { id: "spike", label: "Spike" }, { id: "freeze", label: "Frozen value" },
  { id: "gap", label: "Gap" }, { id: "out_of_range", label: "Impossible value" },
];
type Method = "screening-v1" | "full-v1" | "free";
const METHODS: { id: Method; label: string; help: string }[] = [
  { id: "screening-v1", label: "Screening protocol", help: "48 copies with one fault each and one clean copy: the check for every proposal." },
  { id: "full-v1", label: "Full protocol", help: "About 90 copies with every shape, recovery and length, for comparing detectors." },
  { id: "free", label: "Free draw", help: "Copies with faults of the kinds you choose at drawn places." },
];

/** Labelled copies of one dataset with planted faults, gathered into a suite: by the
 * fault-injection protocol, or drawn freely. */
export function FaultSuiteDialog({ open, dataset, onOpenChange, onCreated }: {
  open: boolean; dataset: DatasetView; onOpenChange: (open: boolean) => void; onCreated: (suite: SuiteView) => void;
}) {
  const [name, setName] = useState(`${dataset.name} · faults`);
  const [method, setMethod] = useState<Method>("screening-v1");
  const [purpose, setPurpose] = useState<"practice" | "test">("practice");
  const [warmup, setWarmup] = useState("");
  const [window, setWindow] = useState("");
  const [copies, setCopies] = useState("8");
  const [perCopy, setPerCopy] = useState("2");
  const [kinds, setKinds] = useState<FaultKind[]>(["step", "drift", "freeze", "gap"]);
  const [cleanShare, setCleanShare] = useState("30");
  const [seed, setSeed] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const protocol = method !== "free";
  const numbers = { copies: Number(copies), perCopy: Number(perCopy), clean: Number(cleanShare), seed: Number(seed),
    warmup: warmup.trim() === "" ? undefined : Number(warmup), window: window.trim() === "" ? undefined : Number(window) };
  const optional = (value: number | undefined, least: number) => value === undefined || (Number.isInteger(value) && value >= least);
  const valid = name.trim() !== "" && Number.isInteger(numbers.seed) && numbers.seed >= 0 && (protocol
    ? optional(numbers.warmup, 1) && optional(numbers.window, 4)
    : kinds.length > 0 && Number.isInteger(numbers.copies) && numbers.copies >= 1 && numbers.copies <= 20
      && Number.isInteger(numbers.perCopy) && numbers.perCopy >= 1 && numbers.perCopy <= 5
      && numbers.clean >= 0 && numbers.clean <= 80);
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const suite = await dojoApi.createFaultSuite(protocol
        ? { dataset_id: dataset.id, name: name.trim(), protocol: method, purpose, seed: numbers.seed,
          ...(numbers.warmup === undefined ? {} : { warmup_values: numbers.warmup }),
          ...(numbers.window === undefined ? {} : { window_values: numbers.window }) }
        : { dataset_id: dataset.id, name: name.trim(), copies: numbers.copies, faults_per_copy: numbers.perCopy, kinds,
          clean_share: numbers.clean / 100, seed: numbers.seed });
      onOpenChange(false);
      onCreated(suite);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy) { setError(""); onOpenChange(next); } }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog dj-dialog">
        <Dialog.Title>Fault suite</Dialog.Title>
        <Dialog.Description className="dj-help">Makes labelled copies of this dataset with faults planted in them, and
          gathers them into a suite, so designs can be compared on your own data even though it has no labels. The same
          seed plants the same faults again.</Dialog.Description>
        <form onSubmit={event => { event.preventDefault(); if (valid && !busy) void submit(); }}>
          <label className="dj-field">Suite name<input required maxLength={120} value={name} disabled={busy}
            onChange={event => setName(event.target.value)} /></label>
          <fieldset className="dj-field"><legend>Faults</legend>
            <div className="dj-choices">{METHODS.map(item => <label key={item.id} className="dj-check">
              <input type="radio" name="fault-method" checked={method === item.id} disabled={busy}
                onChange={() => setMethod(item.id)} />{item.label}</label>)}</div>
            <small className="dj-help">{METHODS.find(item => item.id === method)?.help}</small>
          </fieldset>
          {protocol ? <>
            <p className="dj-help">Sizes are multiples of each reading&apos;s short-term noise and lengths count observations.
              A study on the suite is judged by its false alarms on the clean copy first, then by what it catches per fault
              type beyond chance.</p>
            <div className="dj-field-row">
              <label className="dj-field"><span>Warm-up <small>(observations; empty: 30%)</small></span>
                <input type="number" min={1} step={1} value={warmup} disabled={busy} placeholder="Design's warm-up"
                  onChange={event => setWarmup(event.target.value)} /></label>
              <label className="dj-field"><span>Window <small>(observations; empty: 5%)</small></span>
                <input type="number" min={4} step={1} value={window} disabled={busy} placeholder="Calibration window"
                  onChange={event => setWindow(event.target.value)} /></label>
            </div>
            <div className="dj-field-row">
              <label className="dj-field">Purpose<select value={purpose} disabled={busy}
                onChange={event => setPurpose(event.target.value === "test" ? "test" : "practice")}>
                <option value="practice">Practice: tune designs on it</option>
                <option value="test">Test: report on it, seed drawn by the server</option>
              </select></label>
              {purpose === "practice" && <label className="dj-field">Seed<input type="number" min={0} step={1} value={seed}
                disabled={busy} onChange={event => setSeed(event.target.value)} /></label>}
            </div>
          </> : <>
            <div className="dj-field-row">
              <label className="dj-field">Copies<input type="number" min={1} max={20} value={copies} disabled={busy}
                onChange={event => setCopies(event.target.value)} /></label>
              <label className="dj-field">Faults per copy<input type="number" min={1} max={5} value={perCopy} disabled={busy}
                onChange={event => setPerCopy(event.target.value)} /></label>
            </div>
            <fieldset className="dj-field"><legend>Kinds</legend>
              <div className="dj-choices">{FAULT_KINDS.map(item => <label key={item.id} className="dj-check">
                <input type="checkbox" checked={kinds.includes(item.id)} disabled={busy}
                  onChange={event => setKinds(previous => event.target.checked ? [...previous, item.id]
                    : previous.filter(kind => kind !== item.id))} />{item.label}</label>)}</div>
            </fieldset>
            <div className="dj-field-row">
              <label className="dj-field"><span>Clean start <small>(% of the span, for warm-up)</small></span>
                <input type="number" min={0} max={80} value={cleanShare} disabled={busy}
                  onChange={event => setCleanShare(event.target.value)} /></label>
              <label className="dj-field">Seed<input type="number" min={0} step={1} value={seed} disabled={busy}
                onChange={event => setSeed(event.target.value)} /></label>
            </div>
          </>}
          {error && <p className="dj-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !valid}>{busy ? "Planting faults…" : "Create suite"}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
