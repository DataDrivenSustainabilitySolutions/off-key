import type { Catalog } from "@/types/collection";
import type { SpatialCatalogProjection } from "./catalog";
import type { SpatialNode, SpatialWorkspace } from "./types";

export type CatalogNameTarget =
  | { kind: "source"; source_id: string }
  | { kind: "charger"; source_id: string; charger_id: string }
  | { kind: "sensor"; source_id: string; charger_id: string; sensor_key: string };
export type CatalogNameIndex = ReadonlyMap<string, string>;

export function catalogNameKey(target: CatalogNameTarget): string {
  return JSON.stringify([
    target.kind,
    target.source_id,
    target.kind === "source" ? "" : target.charger_id,
    target.kind === "sensor" ? target.sensor_key : "",
  ]);
}

/** Keep names and stable identities only; never retain broker endpoints in this index. */
export function buildCatalogNameIndex(catalog: Catalog): CatalogNameIndex {
  const labels = new Map<string, string>();
  for (const source of catalog.sources) {
    labels.set(catalogNameKey({ kind: "source", source_id: source.id }), source.label);
    for (const charger of source.chargers) {
      labels.set(catalogNameKey({ kind: "charger", source_id: source.id, charger_id: charger.id }), charger.label);
      for (const sensor of charger.sensors) {
        labels.set(catalogNameKey({ kind: "sensor", source_id: source.id, charger_id: charger.id, sensor_key: sensor.key }), sensor.label);
      }
    }
  }
  return labels;
}

export function catalogNameTarget(node: SpatialNode): CatalogNameTarget | undefined {
  const definition = node.catalog;
  if (!definition) return;
  if (node.kind === "broker") return { kind: "source", source_id: definition.sourceId };
  if ((node.kind === "charger" || (node.kind === "group" && node.id === `group:ambibox:group:${definition.chargerId}`)) && definition.chargerId)
    return { kind: "charger", source_id: definition.sourceId, charger_id: definition.chargerId };
  if (node.kind === "sensor" && definition.chargerId && definition.sensorKey)
    return { kind: "sensor", source_id: definition.sourceId, charger_id: definition.chargerId, sensor_key: definition.sensorKey };
}

export function catalogGroupNameTarget(projection: SpatialCatalogProjection, groupId: string): CatalogNameTarget | undefined {
  const charger = projection.topology.nodes.find((node) => node.kind === "charger" && `ambibox:group:${node.catalog?.chargerId}` === groupId);
  if (charger) return catalogNameTarget(charger);
  const broker = projection.topology.nodes.find((node) => node.kind === "broker" && `ambibox:group:${node.catalog?.sourceId}` === groupId);
  return broker ? catalogNameTarget(broker) : undefined;
}

/** Apply acknowledged database names without replacing topology, layout, or identities. */
export function applyCatalogNames(projection: SpatialCatalogProjection, labels: CatalogNameIndex): SpatialCatalogProjection {
  let changed = false;
  const nodes = projection.topology.nodes.map((node) => {
    const target = catalogNameTarget(node);
    const label = target ? labels.get(catalogNameKey(target)) : undefined;
    if (label === undefined || label === node.label) return node;
    changed = true;
    return { ...node, label, ...(node.kind === "sensor" ? { metric: label } : {}) };
  });
  const groups = projection.groups.map((group) => {
    const target = catalogGroupNameTarget(projection, group.id);
    const label = target ? labels.get(catalogNameKey(target)) : undefined;
    // The persisted presentation format bounds collection titles at 80 chars.
    const name = label?.slice(0, 80);
    if (name === undefined || name === group.name) return group;
    changed = true;
    return { ...group, name };
  });
  return changed ? { ...projection, topology: { ...projection.topology, nodes }, groups } : projection;
}

/** Canonical fleet titles override stale titles; manual colours and placement survive. */
export function applyCatalogWorkspaceNames(workspace: SpatialWorkspace, projection: SpatialCatalogProjection): SpatialWorkspace {
  const canonical = new Map(projection.groups.map((group) => [group.id, group.name]));
  let changed = false;
  const groups = workspace.groups.map((group) => {
    const name = canonical.get(group.id);
    if (name === undefined || name === group.name) return group;
    changed = true;
    return { ...group, name };
  });
  return changed ? { ...workspace, groups } : workspace;
}
