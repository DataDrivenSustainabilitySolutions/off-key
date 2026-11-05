import type { SystemDocument, SystemRuntime } from "@/types/system";
import type { ExplorerNode, NavigationIndex } from "@/domain/system/navigationIndex";

/** Resolve recorded identities to catalogue labels, keeping the identity when the catalogue no longer has it. */
export function reportLabels(document: SystemDocument | undefined, runtime?: SystemRuntime) {
  const connections = new Map(document?.connections.map(item => [item.id, item.label]));
  const devices = new Map(document?.devices.map(item => [item.id, item.label]));
  const entities = new Map<string, string>();
  const readings = new Map<string, string>();
  for (const stream of document?.streams ?? []) {
    const binding = runtime?.bindings?.[stream.id];
    if (!binding) continue;
    const entity = (stream.device_id && devices.get(stream.device_id)) || connections.get(stream.connection_id);
    if (entity && !entities.has(binding.entity_id)) entities.set(binding.entity_id, entity);
    readings.set(`${binding.entity_id}\u0000${binding.telemetry_key}`, stream.label);
  }
  return {
    entity: (id: string) => entities.get(id) ?? id,
    reading: (entityId: string, key: string) => readings.get(`${entityId}\u0000${key}`) ?? key,
  };
}

/** The catalogue node that stands for a recorded entity, so that reports can be scoped to it. */
export function entitySource(index: NavigationIndex, document: SystemDocument | undefined, runtime: SystemRuntime | undefined, entityId: string): ExplorerNode | undefined {
  for (const stream of document?.streams ?? []) {
    if (runtime?.bindings?.[stream.id]?.entity_id !== entityId) continue;
    const nodes = (index.objectKeys.get(stream.device_id ?? stream.connection_id) ?? []).flatMap(key => index.nodes.get(key) ?? []);
    const node = nodes.find(item => stream.device_id ? item.entityKind === "device" : item.kind === "connection");
    if (node) return node;
  }
}

/** The recorded entity behind a selected source, when the selection is exactly one entity. */
export function selectedEntity(streamIds: readonly string[] | undefined, runtime: SystemRuntime | undefined) {
  const ids = new Set((streamIds ?? []).flatMap(id => runtime?.bindings?.[id]?.entity_id ?? []));
  return ids.size === 1 ? [...ids][0] : undefined;
}
