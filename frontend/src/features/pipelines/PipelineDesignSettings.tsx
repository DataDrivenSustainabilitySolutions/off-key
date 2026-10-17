import type { GraphDocument } from "./model";

export function PipelineDesignSettings({
  document,
  readOnly,
  onChange,
}: {
  document: GraphDocument;
  readOnly: boolean;
  onChange: (document: GraphDocument) => void;
}) {
  const definition = document.definition;
  const settings = definition.settings;
  return (
    <details className="pl-design-settings">
      <summary>Input slots and learning settings</summary>
      <p className="pl-help">
        Slots are stable identifiers used by feature selection. Display labels
        can describe their intended meaning. A declared unit requires an exact
        match when binding.
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
                  })
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
                  })
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
      <div className="pl-settings-grid">
        <label className="pl-field">
          <span>
            {definition.strategy === "adaptive_stream"
              ? "Detector learning updates before calibration"
              : "Training observations"}
          </span>
          <input
            type="number"
            min={2}
            max={1_000_000}
            value={settings.training_window_size}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...document,
                definition: {
                  ...definition,
                  settings: {
                    ...settings,
                    training_window_size: Number(event.target.value),
                  },
                },
              })
            }
          />
        </label>
        <label className="pl-field">
          <span>Calibration observations</span>
          <input
            type="number"
            min={1}
            max={1_000_000}
            value={settings.calibration_window_size}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...document,
                definition: {
                  ...definition,
                  settings: {
                    ...settings,
                    calibration_window_size: Number(event.target.value),
                  },
                },
              })
            }
          />
        </label>
        <label className="pl-field">
          <span>Default random seed</span>
          <input
            type="number"
            value={settings.seed ?? ""}
            placeholder="Random"
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...document,
                definition: {
                  ...definition,
                  settings: {
                    ...settings,
                    seed:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  },
                },
              })
            }
          />
        </label>
      </div>
      {definition.strategy === "adaptive_stream" && (
        <p className="pl-help">
          Upstream components initialize first. The configured learning count
          tracks successful updates to the detector; calibration starts only
          after the whole graph is ready.
        </p>
      )}
    </details>
  );
}
