import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import type { PipelineDefinition } from "./contracts";
import { PIPELINE_LIMITS } from "@/types/pipelines.generated";
import { addReading } from "./slots";

export function PipelineInputBindings({ slots, target, bindings, disabled, owned, onChange, onSlotsChange }: {
  slots: PipelineDefinition["input_slots"]; target?: MonitoringTarget; bindings: Record<string, string>;
  disabled: boolean; owned: (id: string) => boolean; onChange: (bindings: Record<string, string>) => void;
  onSlotsChange: (slots: PipelineDefinition["input_slots"], bindings: Record<string, string>) => void;
}) {
  if (!target) return null;
  return <div className="pl-input-bindings" aria-label="Monitoring readings">
    {slots.map((slot) => <div className="pl-reading-binding" key={slot.id}><label className="pl-field">
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
    </label><button type="button" disabled={disabled} aria-label={`Remove reading for ${slot.label}`}
      onClick={() => onSlotsChange(slots.filter((item) => item.id !== slot.id), bindings)}>Remove</button></div>)}
    <label className="pl-field"><span>Add reading</span>
      <select aria-label="Add reading" value="" disabled={disabled || slots.length >= PIPELINE_LIMITS.slots} onChange={(event) => {
        const input = target.inputs.find((input) => input.stream.id === event.target.value);
        if (input) { const next = addReading(slots, bindings, input); onSlotsChange(next.slots, next.bindings); }
      }}>
        <option value="">Choose another reading</option>
        {target.inputs.filter((input) => !slots.some((slot) => bindings[slot.id] === input.stream.id)).map((input) => {
          const reason = input.binding.policy.mode === "off" ? "collection off" : owned(input.stream.id) ? "already monitored" : "";
          return <option key={input.stream.id} value={input.stream.id} disabled={!!reason}>
            {input.stream.label}{input.stream.unit ? ` · ${input.stream.unit}` : ""}{reason ? ` (${reason})` : ""}
          </option>;
        })}
      </select>
    </label>
    {!slots.length && <p className="pl-help">Add at least one reading to monitor.</p>}
  </div>;
}
