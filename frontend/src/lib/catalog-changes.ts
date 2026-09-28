import type { Catalog, CollectionPolicy } from "@/types/collection";

export function policyLabel(policy: CollectionPolicy | null): string {
  if (!policy) return "Use default";
  if (policy.mode === "off") return "Off";
  if (policy.mode === "original") return "Original rate";
  return `Latest every ${policy.interval_seconds}s`;
}

// A removed parent already names the scope of its removed children.
export function catalogRemovals(before: Catalog, after: Catalog): string[] {
  const sources = new Set(after.sources.map((source) => source.id));
  const chargers = new Map(
    after.sources.flatMap((source) =>
      source.chargers.map((charger) => [charger.id, charger] as const),
    ),
  );
  const removed: string[] = [];
  for (const source of before.sources) {
    if (!sources.has(source.id)) {
      removed.push(`Broker ${source.label}`);
      continue;
    }
    for (const charger of source.chargers) {
      const next = chargers.get(charger.id);
      if (!next) {
        removed.push(`Charger ${charger.label}`);
        continue;
      }
      const keys = new Set(next.sensors.map((sensor) => sensor.key));
      for (const sensor of charger.sensors) {
        if (!keys.has(sensor.key))
          removed.push(`${charger.label} · ${sensor.label}`);
      }
    }
  }
  return removed;
}
