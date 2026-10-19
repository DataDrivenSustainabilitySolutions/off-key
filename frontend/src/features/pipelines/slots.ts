import type { MonitoringTarget } from "../monitoring/serviceModel";
import type { PipelineDefinition } from "./contracts";

/** One slot per enabled reading of the target; the first keeps the design's own slot ID. */
export function targetSlots(
  target: MonitoringTarget | undefined,
  slots: PipelineDefinition["input_slots"],
  reading?: string,
): PipelineDefinition["input_slots"] | undefined {
  const readings = target?.inputs.filter((input) => input.binding.policy.mode !== "off"
    && (!reading || !target.inputs.some((item) => item.stream.id === reading) || input.stream.id === reading)) ?? [];
  if (!readings.length) return undefined;
  const used = new Set<string>();
  return readings.map((input, index) => {
    let id = index === 0 ? (slots[0]?.id ?? "input_1") : `input_${index + 1}`;
    for (let suffix = index + 1; used.has(id); suffix++) id = `input_${suffix}`;
    used.add(id);
    return { id, label: input.stream.label, unit: input.stream.unit ?? null };
  });
}

export const sameSlots = (left: PipelineDefinition["input_slots"], right: PipelineDefinition["input_slots"]) =>
  left.length === right.length && left.every((slot, index) =>
    slot.label === right[index]!.label && (slot.unit ?? null) === (right[index]!.unit ?? null));

