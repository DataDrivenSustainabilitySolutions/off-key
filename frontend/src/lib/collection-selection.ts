import type { Catalog, CollectionPolicy } from "@/types/collection";

export const validPolicy = (policy: CollectionPolicy) =>
  policy.mode !== "sample" ||
  (Number.isInteger(policy.interval_seconds) &&
    policy.interval_seconds >= 1 &&
    policy.interval_seconds <= 3600);

export function setMeasurementPolicies(
  catalog: Catalog,
  selected: ReadonlySet<string>,
  policy: CollectionPolicy,
): Catalog {
  return {
    ...catalog,
    sources: catalog.sources.map((source) => ({
      ...source,
      chargers: source.chargers.map((charger) => ({
        ...charger,
        sensors: charger.sensors.map((sensor) =>
          selected.has(`${charger.id}:${sensor.key}`)
            ? { ...sensor, policy }
            : sensor,
        ),
      })),
    })),
  };
}
