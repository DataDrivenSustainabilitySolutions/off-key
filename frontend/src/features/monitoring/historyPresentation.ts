import type { PipelineServiceView } from "@/types/pipelines.generated";

export interface HistoryPresentation {
  bindings: Record<string, string>;
  rawInputs: Record<string, string>;
  intervalLabel: string;
}

/** Provenance, never labels or coincidentally equal values, decides whether a
 * detector input duplicates a reading. Unknown/transformed features stay separate. */
export function historyPresentation(view: PipelineServiceView): HistoryPresentation {
  const bindings = Object.fromEntries((view.run?.execution?.bindings ?? view.run?.binding_metadata?.readings ?? [])
    .map(input => [input.slot_id, input.reading_id]));
  const rawInputs: Record<string, string> = {};
  const detectors = (view.definition.nodes ?? []).filter(node => node.kind === "detector");
  for (const detector of detectors) {
    const parent = view.definition.edges?.find(edge => edge.target === detector.id)?.source;
    for (const feature of parent ? view.validation?.features?.[parent] ?? [] : []) {
      const reading = feature.raw && feature.slots.length === 1 ? bindings[feature.slots[0]!] : undefined;
      if (!reading) continue;
      rawInputs[`input:${detector.id}:${feature.name}`] = reading;
      if (detectors.length === 1) rawInputs[`input::${feature.name}`] = reading;
    }
  }
  const calibration = view.definition.nodes?.find(node => node.kind === "calibration")?.component;
  const names: Record<string, string> = { "calibrate.nexcp": "NexCP interval", "calibrate.aci": "ACI interval",
    "calibrate.fixed_split": "Calibrated interval" };
  return { bindings, rawInputs, intervalLabel: names[calibration ?? ""] ?? "Calibrated interval" };
}
