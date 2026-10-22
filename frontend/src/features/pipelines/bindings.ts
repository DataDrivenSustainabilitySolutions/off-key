import type { ActiveService } from "@/types/monitoring";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import type { PipelineDefinition, PipelineServiceView } from "./contracts";

/** Suggest only unambiguous matches; never guess between two equivalent readings. */
export function suggestBindings(slots: PipelineDefinition["input_slots"], target?: MonitoringTarget, previous: Record<string, string> = {}) {
  const bindings: Record<string, string> = {};
  const used = new Set<string>();
  for (const slot of slots) {
    const candidates = target?.inputs.filter((input) => input.binding.policy.mode !== "off"
      && !used.has(input.stream.id) && (slot.unit == null || slot.unit === input.stream.unit)) ?? [];
    const exact = candidates.filter((input) => input.stream.label === slot.label);
    const chosen = candidates.find((input) => input.stream.id === previous[slot.id])
      ?? (exact.length === 1 ? exact[0] : candidates.length === 1 ? candidates[0] : undefined);
    if (chosen) { bindings[slot.id] = chosen.stream.id; used.add(chosen.stream.id); }
  }
  return bindings;
}

export function bindingsReady(slots: PipelineDefinition["input_slots"], target: MonitoringTarget | undefined,
  bindings: Record<string, string>, owned: (id: string) => boolean) {
  return slots.length > 0 && new Set(slots.map((slot) => bindings[slot.id])).size === slots.length
    && slots.every((slot) => target?.inputs.some((input) => input.stream.id === bindings[slot.id]
      && input.binding.policy.mode !== "off" && !owned(input.stream.id)
      && (slot.unit == null || slot.unit === input.stream.unit)));
}

/** The predecessor run's slot-to-reading bindings. */
export const previousBindings = (predecessor?: PipelineServiceView): Record<string, string> =>
  Object.fromEntries((predecessor?.run?.execution?.bindings ?? []).map((binding) => [binding.slot_id, binding.reading_id]));

/** Whether another active service (not the one being replaced) already monitors a reading. */
export function readingOwnedElsewhere(services: ActiveService[], byStream: Map<string, Set<string>>, replaceServiceId?: string) {
  const active = new Set(services.filter((service) => service.status && service.id !== replaceServiceId).map((service) => service.id));
  return (readingId: string) => [...(byStream.get(readingId) ?? [])].some((id) => active.has(id));
}

/**
 * The target a replacement starts on: the workspace's explicit target, else
 * the entity of the predecessor's first binding, else the target that holds
 * any of the predecessor's readings today.
 */
export const predecessorEntity = (predecessor?: PipelineServiceView) => predecessor?.run?.execution?.bindings[0]?.entity_id;

export const predecessorTarget = (targets: MonitoringTarget[], predecessor?: PipelineServiceView) =>
  targets.find((target) => target.inputs.some((input) =>
    predecessor?.run?.execution?.bindings.some((binding) => binding.reading_id === input.stream.id)))?.id;

