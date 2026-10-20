import type { MonitoringTarget } from "../monitoring/serviceModel";
import type { PipelineDefinition } from "./contracts";

export function PipelineInputBindings({ slots, target, bindings, disabled, owned, onChange }: {
  slots: PipelineDefinition["input_slots"]; target?: MonitoringTarget; bindings: Record<string, string>;
  disabled: boolean; owned: (id: string) => boolean; onChange: (bindings: Record<string, string>) => void;
}) {
  if (!target) return null;
  return <div className="pl-input-bindings" aria-label="Monitoring readings">
    {slots.map((slot) => <label className="pl-field" key={slot.id}>
      <span>{slot.label}{slot.unit && <small>{slot.unit}</small>}</span>
      <select aria-label={`Reading for ${slot.label}`} value={bindings[slot.id] ?? ""} disabled={disabled}
        onChange={(event) => onChange({ ...bindings, [slot.id]: event.target.value })}>
        <option value="">Choose a reading</option>
        {target.inputs.map((input) => {
          const reason = input.binding.policy.mode === "off" ? "collection off" : owned(input.stream.id) ? "already monitored"
            : slot.unit != null && slot.unit !== input.stream.unit ? "unit mismatch"
              : slots.some((other) => other.id !== slot.id && bindings[other.id] === input.stream.id) ? "already selected" : "";
          return <option key={input.stream.id} value={input.stream.id} disabled={!!reason}>
            {input.stream.label}{input.stream.unit ? ` · ${input.stream.unit}` : ""}{reason ? ` (${reason})` : ""}
          </option>;
        })}
      </select>
    </label>)}
    {!slots.length && <p className="pl-help">Add an input in Learning settings or choose an entity with collection enabled.</p>}
  </div>;
}
