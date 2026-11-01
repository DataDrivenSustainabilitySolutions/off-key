import type { MonitoringInput, MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { PIPELINE_LIMITS } from "@/types/pipelines.generated";
import type { PipelineDefinition } from "./contracts";

/** A feature name from a reading's label, such as "DC voltage" to dc_voltage. Steps
 * refer to features by these names, so they stay readable and valid slot IDs. */
export function featureName(label: string) {
  const slug = label.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+/, "").slice(0, 48).replace(/_+$/, "");
  if (!slug) return "reading";
  return /^[a-z]/.test(slug) ? slug : `reading_${slug}`;
}

function uniqueName(label: string, taken: (id: string) => boolean) {
  const base = featureName(label);
  let id = base;
  for (let suffix = 2; taken(id); suffix++) id = `${base}_${suffix}`;
  return id;
}

/** One slot per enabled reading of the target, named after the reading. */
export function targetInputs(target: MonitoringTarget | undefined, reading?: string) {
  const readings = target?.inputs.filter((input) => input.binding.policy.mode !== "off"
    && (!reading || !target.inputs.some((item) => item.stream.id === reading) || input.stream.id === reading)) ?? [];
  if (!readings.length) return undefined;
  const used = new Set<string>();
  const next = readings.slice(0, PIPELINE_LIMITS.slots).map((input) => {
    const id = uniqueName(input.stream.label, (name) => used.has(name));
    used.add(id);
    return { id, label: input.stream.label, unit: input.stream.unit ?? null };
  });
  return { slots: next, bindings: Object.fromEntries(next.map((slot, index) => [slot.id, readings[index]!.stream.id])) };
}

/** Keep removed bindings for undo/reselection; never give their IDs to a different reading. */
export function addReading(slots: PipelineDefinition["input_slots"], bindings: Record<string, string>, input: MonitoringInput) {
  if (slots.length >= PIPELINE_LIMITS.slots || slots.some((slot) => bindings[slot.id] === input.stream.id)) return { slots, bindings };
  const previous = Object.keys(bindings).find((id) => bindings[id] === input.stream.id && !slots.some((slot) => slot.id === id));
  const id = previous ?? uniqueName(input.stream.label, (name) =>
    slots.some((slot) => slot.id === name) || Object.prototype.hasOwnProperty.call(bindings, name));
  return { slots: [...slots, { id, label: input.stream.label, unit: input.stream.unit ?? null }],
    bindings: { ...bindings, [id]: input.stream.id } };
}

export function selectReadings(target: MonitoringTarget, slots: PipelineDefinition["input_slots"],
  bindings: Record<string, string>, selected: string[]) {
  let next = { slots: slots.filter((slot) => selected.includes(bindings[slot.id]!)), bindings };
  for (const input of target.inputs) {
    if (selected.includes(input.stream.id) && input.binding.policy.mode !== "off"
      && !next.slots.some((slot) => next.bindings[slot.id] === input.stream.id) && next.slots.length < PIPELINE_LIMITS.slots)
      next = addReading(next.slots, next.bindings, input);
  }
  return next;
}

type Slots = PipelineDefinition["input_slots"];

/** A design-settings slot takes the first free input_N among the slot ids. */
export function addSlot(slots: Slots): Slots {
  let index = 1;
  while (slots.some((slot) => slot.id === `input_${index}`)) index++;
  return [...slots, { id: `input_${index}`, label: `Input ${index}`, unit: null }];
}

export const renameSlot = (slots: Slots, id: string, label: string): Slots =>
  slots.map((slot) => (slot.id === id ? { ...slot, label } : slot));

/** An empty unit means unspecified. */
export const setSlotUnit = (slots: Slots, id: string, unit: string): Slots =>
  slots.map((slot) => (slot.id === id ? { ...slot, unit: unit || null } : slot));

export const removeSlot = (slots: Slots, id: string): Slots => slots.filter((slot) => slot.id !== id);
