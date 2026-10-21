import { useId, useState } from "react";
import type { GraphDocument } from "./model";
import type { HistoryMode } from "./useGraphEditor";

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
  readOnly,
  onChange,
}: {
  document: GraphDocument;
  readOnly: boolean;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
}) {
  const definition = document.definition;
  const settings = definition.settings;
  const setting = (change: Partial<typeof settings>, field: string) =>
    onChange({
      ...document,
      definition: { ...definition, settings: { ...settings, ...change } },
    }, `setting:${field}`);
  return (
    <>
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
      {definition.strategy === "adaptive_stream" && (
        <p className="pl-help">
          Upstream components initialize first. The configured learning count
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
                    onChange({
                      ...document,
                      definition: {
                        ...definition,
                        input_slots: definition.input_slots.map((item) =>
                          item.id === slot.id
                            ? { ...item, label: event.target.value }
                            : item,
                        ),
                      },
                    }, `slot-label:${slot.id}`)
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
                    onChange({
                      ...document,
                      definition: {
                        ...definition,
                        input_slots: definition.input_slots.map((item) =>
                          item.id === slot.id
                            ? { ...item, unit: event.target.value || null }
                            : item,
                        ),
                      },
                    }, `slot-unit:${slot.id}`)
                  }
                />
              </label>
              {!readOnly && (
                <button
                  type="button"
                  aria-label={`Remove slot ${slot.id}`}
                  onClick={() =>
                    onChange({
                      ...document,
                      definition: {
                        ...definition,
                        input_slots: definition.input_slots.filter(
                          (item) => item.id !== slot.id,
                        ),
                      },
                    })
                  }
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
            disabled={definition.input_slots.length >= 100}
            onClick={() => {
              let index = 1;
              while (
                definition.input_slots.some(
                  (slot) => slot.id === `input_${index}`,
                )
              )
                index++;
              onChange({
                ...document,
                definition: {
                  ...definition,
                  input_slots: [
                    ...definition.input_slots,
                    { id: `input_${index}`, label: `Input ${index}`, unit: null },
                  ],
                },
              });
            }}
          >
            Add input slot
          </button>
        )}
      </details>
    </>
  );
}
