import type { Catalog, CollectionPolicy } from "@/types/collection";
import { effectivePolicy, pausedPolicy } from "@/types/collection";

export function collectionMeasurements(
  catalog: Catalog,
  chargerIds: ReadonlySet<string>,
) {
  return catalog.sources.flatMap((source) =>
    source.chargers
      .filter((charger) => chargerIds.has(charger.id))
      .flatMap((charger) =>
        charger.sensors.map((sensor) => ({
          id: `${charger.id}:${sensor.key}`,
          chargerId: charger.id,
          charger: charger.label,
          sensor,
          policy: effectivePolicy(catalog, charger, sensor),
        })),
      ),
  );
}

// The editor specifies the complete selection for these chargers. Pause their
// defaults so other measurements cannot inherit an enabled policy.
export function configureCollection(
  catalog: Catalog,
  chargerIds: ReadonlySet<string>,
  policies: ReadonlyMap<string, CollectionPolicy>,
): Catalog {
  return {
    ...catalog,
    sources: catalog.sources.map((source) => ({
      ...source,
      chargers: source.chargers.map((charger) =>
        chargerIds.has(charger.id)
          ? {
              ...charger,
              policy: pausedPolicy,
              sensors: charger.sensors.map((sensor) => {
                const policy = policies.get(`${charger.id}:${sensor.key}`);
                return {
                  ...sensor,
                  policy: policy?.mode === "off" ? null : (policy ?? null),
                };
              }),
            }
          : charger,
      ),
    })),
  };
}
