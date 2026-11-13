import { useId, useState } from "react";
import { AlarmBudgetSetting } from "./AlarmBudgetSetting";
import type { PipelineCatalog } from "./contracts";
import { hasFittedDetector, hasStreamingDetector, learningWindow } from "./learning";
import { PIPELINE_LIMITS, type GraphDocument } from "./model";
import { addSlot, removeSlot, renameSlot, setSlotUnit } from "./slots";
import { observationCount, roughDuration, startupSummary, type Startup } from "./startup";
import type { HistoryMode } from "./types";

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
        {phases.some((phase) => phase.id === "learning") && "Learned steps before the detector can need a few observations of their own first."}
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
  shortfall,
  shadow,
  onShadow,
  readOnly,
  onChange,
}: {
  document: GraphDocument;
  /** Tells how the design's detectors learn, which names the learning window. */
  catalog?: PipelineCatalog;
  startup?: Startup;
  /** What the check says when the calibration window is too short for the alarm budget. */
  shortfall?: string;
  /** Whether the service starts in shadow, where the page starts a service. */
  shadow?: boolean;
  onShadow?: (shadow: boolean) => void;
  readOnly: boolean;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
}) {
  const definition = document.definition;
  const settings = definition.settings;
  // Without the catalog, a design reads as one that learns continuously.
  const fitted = !!catalog && hasFittedDetector(definition, catalog.components);
  const streaming = !catalog || hasStreamingDetector(definition, catalog.components);
  // Detectors that follow a rule have nothing to learn, so the design has no learning window.
  const untrained = !!catalog && learningWindow(definition, catalog.components) === "none";
  const setting = (change: Partial<typeof settings>, field: string) =>
    onChange({
      ...document,
      definition: { ...definition, settings: { ...settings, ...change } },
    }, `setting:${field}`);
  const setSlots = (input_slots: typeof definition.input_slots, history?: HistoryMode) =>
    onChange({ ...document, definition: { ...definition, input_slots } }, history);
  return (
    <>
      {(catalog || onShadow) && <section className="pl-alarms">
        {catalog && <AlarmBudgetSetting document={document} components={catalog.components} interval={startup?.interval}
          gated={startup?.gated} shortfall={shortfall} readOnly={readOnly} onChange={onChange} />}
        {onShadow && <label className="pl-check">
          <input type="checkbox" checked={!!shadow} disabled={readOnly} onChange={(event) => onShadow(event.target.checked)} />
          <span>Shadow run<small>Records the alarms it would raise and raises none. An update without it takes the service live.</small></span>
        </label>}
      </section>}
      {catalog && <p className="pl-help pl-learning-note">
        {untrained
          ? "The detectors follow a rule and learn nothing, so calibration starts with the first observation."
          : fitted && streaming
            ? "Some detectors are fitted once on the training window and others keep learning. They meet at the calibration step."
            : fitted ? "The detectors are fitted once on the training window and then stay as they are."
              : "The detectors take in every observation and keep adapting."}
        {" "}Each detector's settings choose its model, and with it how it learns.
      </p>}
      <div className="pl-settings-grid">
        {!untrained && <NumberSetting
          label={fitted && streaming ? "Training observations and learning updates"
            : fitted ? "Training observations" : "Detector learning updates before calibration"}
          min={2}
          max={1_000_000}
          value={settings.training_window_size}
          disabled={readOnly}
          onChange={(value) => setting({ training_window_size: value ?? settings.training_window_size }, "training")}
        />}
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
      {streaming && !untrained && (
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
