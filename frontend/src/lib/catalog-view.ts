import type { Catalog } from "@/types/collection";

export type CatalogFilter = {
  query: string;
  evidence: "all" | "observed" | "candidate";
};

// Views retain the original objects. Edits always target IDs in the full catalog.
export function catalogView(catalog: Catalog, filter: CatalogFilter) {
  const query = filter.query.trim().toLowerCase();
  const matches = (...values: string[]) =>
    values.some((value) => value.toLowerCase().includes(query));
  return catalog.sources.flatMap((source) => {
    if (filter.evidence === "observed" && !source.verified) return [];
    if (filter.evidence === "candidate" && source.verified) return [];
    const sourceMatches = matches(source.label, source.host, source.id);
    const chargers = source.chargers.filter(
      (charger) =>
        sourceMatches ||
        matches(charger.label, charger.local_id, charger.id) ||
        charger.sensors.some((sensor) =>
          matches(
            sensor.label,
            sensor.key,
            sensor.category,
            sensor.upstream_topic,
          ),
        ),
    );
    return sourceMatches || chargers.length > 0 ? [{ source, chargers }] : [];
  });
}
