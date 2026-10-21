import type { MonitoringInput, MonitoringTarget } from "../monitoring/serviceModel";
import type { PipelineDefinition } from "./contracts";

/** One slot per enabled reading of the target; the first keeps the design's own slot ID. */
export function targetInputs(
  target: MonitoringTarget | undefined,
  slots: PipelineDefinition["input_slots"],
  reading?: string,
) {
  const readings = target?.inputs.filter((input) => input.binding.policy.mode !== "off"
    && (!reading || !target.inputs.some((item) => item.stream.id === reading) || input.stream.id === reading)) ?? [];
  if (!readings.length) return undefined;
  const used = new Set<string>();
  const next = readings.slice(0, 100).map((input, index) => {
    let id = index === 0 ? (slots[0]?.id ?? "input_1") : `input_${index + 1}`;
    for (let suffix = index + 1; used.has(id); suffix++) id = `input_${suffix}`;
    used.add(id);
    return { id, label: input.stream.label, unit: input.stream.unit ?? null };
  });
  return { slots: next, bindings: Object.fromEntries(next.map((slot, index) => [slot.id, readings[index]!.stream.id])) };
}

/** Keep removed bindings for undo/reselection; never give their IDs to a different reading. */
export function addReading(slots: PipelineDefinition["input_slots"], bindings: Record<string, string>, input: MonitoringInput) {
  if (slots.length >= 100 || slots.some((slot) => bindings[slot.id] === input.stream.id)) return { slots, bindings };
  const previous = Object.keys(bindings).find((id) => bindings[id] === input.stream.id && !slots.some((slot) => slot.id === id));
  let id = previous ?? "input_1";
  for (let index = 2; !previous && (slots.some((slot) => slot.id === id) || id in bindings); index++) id = `input_${index}`;
  return { slots: [...slots, { id, label: input.stream.label, unit: input.stream.unit ?? null }],
    bindings: { ...bindings, [id]: input.stream.id } };
}

export function selectReadings(target: MonitoringTarget, slots: PipelineDefinition["input_slots"],
  bindings: Record<string, string>, selected: string[]) {
  let next = { slots: slots.filter((slot) => selected.includes(bindings[slot.id]!)), bindings };
  for (const input of target.inputs) {
    if (selected.includes(input.stream.id) && input.binding.policy.mode !== "off"
      && !next.slots.some((slot) => next.bindings[slot.id] === input.stream.id) && next.slots.length < 100)
      next = addReading(next.slots, next.bindings, input);
  }
  return next;
}
