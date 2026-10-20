import type { MonitoringTarget } from "../monitoring/serviceModel";
import type { PipelineDefinition } from "./contracts";

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
