import type {
  Catalog,
  CatalogCharger,
  CatalogSource,
} from "@/types/collection";

export type CatalogFilter = {
  query: string;
  evidence: "all" | "observed" | "candidate";
  category: string;
};

const matches = (query: string, ...values: string[]) =>
  values.some((value) =>
    value.toLowerCase().includes(query.trim().toLowerCase()),
  );

export function visibleMeasurements(
  source: CatalogSource,
  charger: CatalogCharger,
  filter: CatalogFilter,
) {
  const parentMatches = matches(
    filter.query,
    source.label,
    source.host,
    source.id,
    charger.label,
    charger.local_id,
    charger.id,
  );
  return charger.sensors.filter(
    (sensor) =>
      (!filter.category || sensor.category === filter.category) &&
      (parentMatches ||
        matches(
          filter.query,
          sensor.label,
          sensor.key,
          sensor.category,
          sensor.upstream_topic,
        )),
  );
}

// Views retain the original objects. Edits always target IDs in the full catalog.
export function catalogView(catalog: Catalog, filter: CatalogFilter) {
  return catalog.sources.flatMap((source) => {
    if (filter.evidence === "observed" && !source.verified) return [];
    if (filter.evidence === "candidate" && source.verified) return [];
    const sourceMatches =
      !filter.category &&
      matches(filter.query, source.label, source.host, source.id);
    const chargers = source.chargers.filter(
      (charger) =>
        (!filter.category &&
          (sourceMatches ||
            matches(
              filter.query,
              charger.label,
              charger.local_id,
              charger.id,
            ))) ||
        visibleMeasurements(source, charger, filter).length > 0,
    );
    return sourceMatches || chargers.length > 0 ? [{ source, chargers }] : [];
  });
}
