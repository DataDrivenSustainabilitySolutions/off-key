import { useId, useState } from "react";
import type { PipelineCatalog } from "./contracts";
import { nodeOptionLabeler, PIPELINE_LIMITS, type GraphDocument } from "./model";
import { strategyLabel } from "./semantics";
import { addSlot, removeSlot, renameSlot, setSlotUnit } from "./slots";
import { observationCount, roughDuration, startupSummary, type Startup } from "./startup";
import { convertStrategy, type Strategy } from "./strategy";
import type { HistoryMode } from "./types";

const STRATEGIES: Strategy[] = ["static_baseline", "adaptive_stream"];

/** Learning and calibration as one bar, with their lengths and durations. */
function StartupTimeline({ startup }: { startup: Startup }) {
  const { phases, observations, interval, gated } = startup;
  const heading = useId();
  return (
    <section className="pl-startup" aria-labelledby={heading}>
      <div className="pl-startup-heading">
        <h4 id={heading}>Before the first alarm</h4>
        <span>{gated ? "At least " : ""}{observationCount(observations)}{interval ? ` · ${startupSummary(startup)}` : ""}</span>
      </div>
      <div className="pl-startup-bar" aria-hidden="true">
        {phases.map((phase) => <span key={phase.id} className={`is-${phase.id}`} style={{ flexGrow: phase.observations }} />)}
      </div>
      <dl>
        {phases.map((phase) => <div key={phase.id} className={`is-${phase.id}`}>
          <dt>{phase.label}</dt>
          <dd>{phase.observations.toLocaleString()}{interval ? ` · ≈ ${roughDuration(phase.observations * interval)}` : ""}</dd>
        </div>)}
      </dl>
      <p className="pl-help">
        {interval
          ? `Durations use the slowest reading's typical interval of ${roughDuration(interval)}. `
          : "Durations appear once the chosen readings report how often they arrive. "}
        Learned steps before the detector can need a few observations of their own first.
        {gated && " A Gate holds back the observations its condition rejects, and they do not count, so the start can take longer."}
      </p>
    </section>
  );
}

/** Keeps the typed text while it is incomplete; only valid numbers reach the design. */
function NumberSetting({
  label, value, min, max, placeholder, nullable, disabled, onChange,
}: {
  label: string;
  value: number | null | undefined;
  min?: number;
  max?: number;
  placeholder?: string;
  nullable?: boolean;
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  const errorId = useId();
  const [text, setText] = useState<string>();
  const shown = text ?? (value == null ? "" : String(value));
  const parsed = shown.trim() === "" ? null : Number(shown);
  const error = parsed === null
    ? nullable ? "" : "Enter a number."
    : !Number.isInteger(parsed) ? "Enter a whole number."
      : min !== undefined && parsed < min ? `Use at least ${min.toLocaleString()}.`
        : max !== undefined && parsed > max ? `Use at most ${max.toLocaleString()}.` : "";
  return (
    <label className="pl-field">
      <span>{label}</span>
      <input
        type="number"
        inputMode="numeric"
        step={1}
        min={min}
        max={max}
        value={shown}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={!!error}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          const number = next.trim() === "" ? null : Number(next);
          if (number === null ? nullable : Number.isInteger(number)
            && (min === undefined || number >= min) && (max === undefined || number <= max))
            onChange(number);
        }}
        onBlur={() => setText(undefined)}
      />
      {error && <small className="pl-field-error" id={errorId}>{error} The last valid value is kept.</small>}
    </label>
  );
}

export function PipelineDesignSettings({
  document,
  catalog,
  startup,
  readOnly,
  onChange,
}: {
  document: GraphDocument;
  /** Offers the strategy switch, which needs every component's counterpart. */
  catalog?: PipelineCatalog;
  startup?: Startup;
  readOnly: boolean;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
}) {
  const definition = document.definition;
  const settings = definition.settings;
  const [switched, setSwitched] = useState<{ strategy: Strategy; message: string }>();
  const strategyLabelId = useId();
  const switchTo = (strategy: Strategy) => {
    if (!catalog || strategy === definition.strategy) return;
    const change = convertStrategy(document, strategy, catalog);
    const name = nodeOptionLabeler(change.document, catalog.components);
    const missing = change.unconverted.map((id) => name(definition.nodes.find((node) => node.id === id)));
    const moved = change.converted.length;
    const kind = strategy === "adaptive_stream" ? "adaptive" : "static";
    setSwitched({ strategy, message: [
      `Switched to ${strategyLabel(strategy)}.`,
      moved === 1 ? `1 step moved to its ${kind} counterpart.`
        : moved ? `${moved} steps moved to their ${kind} counterparts.` : "",
      missing.length ? `No counterpart for ${missing.join(", ")}; replace ${missing.length === 1 ? "it" : "them"} to apply.` : "",
      "Undo switches back.",
    ].filter(Boolean).join(" ") });
    onChange(change.document);
  };
  const setting = (change: Partial<typeof settings>, field: string) =>
    onChange({
      ...document,
      definition: { ...definition, settings: { ...settings, ...change } },
    }, `setting:${field}`);
  const setSlots = (input_slots: typeof definition.input_slots, history?: HistoryMode) =>
    onChange({ ...document, definition: { ...definition, input_slots } }, history);
  return (
    <>
      {catalog && <div className="pl-field pl-strategy-field">
        <span id={strategyLabelId}>Strategy</span>
        <div className="pl-segmented" role="group" aria-labelledby={strategyLabelId}>
          {STRATEGIES.map((strategy) => <button key={strategy} type="button" aria-pressed={definition.strategy === strategy}
            disabled={readOnly} onClick={() => switchTo(strategy)}>{strategyLabel(strategy)}</button>)}
        </div>
        <small className="pl-help">
          {definition.strategy === "adaptive_stream" ? "Learns from live readings and keeps adapting." : "Learns a baseline, then monitors against it."}
          {" "}Switching moves learned steps to their counterparts and changes the detector.
        </small>
        {switched?.strategy === definition.strategy && <p className="pl-notice" role="status">{switched.message}</p>}
      </div>}
      <div className="pl-settings-grid">
        <NumberSetting
          label={definition.strategy === "adaptive_stream"
            ? "Detector learning updates before calibration"
            : "Training observations"}
          min={2}
          max={1_000_000}
          value={settings.training_window_size}
          disabled={readOnly}
          onChange={(value) => setting({ training_window_size: value ?? settings.training_window_size }, "training")}
        />
        <NumberSetting
          label="Calibration observations"
          min={1}
          max={1_000_000}
          value={settings.calibration_window_size}
          disabled={readOnly}
          onChange={(value) => setting({ calibration_window_size: value ?? settings.calibration_window_size }, "calibration")}
        />
        <NumberSetting
          label="Default random seed"
          nullable
          placeholder="Random"
          value={settings.seed}
          disabled={readOnly}
          onChange={(value) => setting({ seed: value }, "seed")}
        />
      </div>
      {startup && <StartupTimeline startup={startup} />}
      {definition.strategy === "adaptive_stream" && (
        <p className="pl-help">
          Upstream steps initialize first. The configured learning count
          tracks successful updates to the detector; calibration starts only
          after the whole graph is ready.
        </p>
      )}
      <details className="pl-design-settings">
        <summary>Input slots</summary>
        <p className="pl-help">
          Units must match the bound readings.
        </p>
        <div className="pl-slots">
          {definition.input_slots.map((slot) => (
            <div className="pl-slot" key={slot.id}>
              <code>{slot.id}</code>
              <label className="pl-field">
                <span>Slot label</span>
                <input
                  maxLength={120}
                  aria-label={`Label for ${slot.id}`}
                  value={slot.label}
                  disabled={readOnly}
                  onChange={(event) =>
                    setSlots(renameSlot(definition.input_slots, slot.id, event.target.value), `slot-label:${slot.id}`)
                  }
                />
              </label>
              <label className="pl-field">
                <span>Expected unit</span>
                <input
                  maxLength={32}
                  aria-label={`Unit for ${slot.id}`}
                  value={slot.unit ?? ""}
                  placeholder="Unspecified"
                  disabled={readOnly}
                  onChange={(event) =>
                    setSlots(setSlotUnit(definition.input_slots, slot.id, event.target.value), `slot-unit:${slot.id}`)
                  }
                />
              </label>
              {!readOnly && (
                <button
                  type="button"
                  aria-label={`Remove slot ${slot.id}`}
                  onClick={() => setSlots(removeSlot(definition.input_slots, slot.id))}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
        {!readOnly && (
          <button
            type="button"
            disabled={definition.input_slots.length >= PIPELINE_LIMITS.slots}
            onClick={() => setSlots(addSlot(definition.input_slots))}
          >
            Add input slot
          </button>
        )}
      </details>
    </>
  );
}
