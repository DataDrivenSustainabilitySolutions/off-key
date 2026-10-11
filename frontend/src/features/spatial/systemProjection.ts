import { createDefaultWorkspace, workspaceValue } from "./model";
import { validateSystemDocument } from "./systemDocument";
import type { SystemDocument, SystemStream } from "./systemTypes";
import type {
  SpatialGroup,
  SpatialNode,
  SpatialWorkspace,
  Topology,
} from "./types";

export type SystemProjection = {
  document: SystemDocument;
  topology: Topology;
  workspace: SpatialWorkspace;
  groups: SpatialGroup[];
  datasetKey: string;
  summary: {
    connections: number;
    devices: number;
    streams: number;
    groups: number;
    valueTypes: Record<SystemStream["value_type"], number>;
  };
};

function fingerprint(value: string): string {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
    second ^= second >>> 13;
  }
  return `${(first >>> 0).toString(16).padStart(8, "0")}${(second >>> 0).toString(16).padStart(8, "0")}`;
}

/** Presentation is derived from configuration; no synthetic rates or readings. */
export function projectSystemDocument(input: SystemDocument): SystemProjection {
  const document = validateSystemDocument(input);
  const memberships = new Map<string, string>();
  for (const group of document.groups) {
    for (const member of group.member_ids) {
      if (!memberships.has(member)) memberships.set(member, group.id);
    }
  }
  const groups: SpatialGroup[] = document.groups.map((entry) => ({
    id: entry.id,
    name: entry.label.slice(0, 80),
    color: entry.color ?? "#7d9b8b",
    collapsed: false,
    locked: false,
  }));
  const entities = [
    ...document.connections,
    ...document.devices,
    ...document.streams,
  ];
  let ungrouped = "system:ungrouped";
  const existingIds = new Set(
    [...entities, ...document.groups].map((entry) => entry.id),
  );
  let ungroupedIndex = 0;
  while (existingIds.has(ungrouped) || existingIds.has(`group:${ungrouped}`)) {
    ungroupedIndex += 1;
    ungrouped = `system:ungrouped:${ungroupedIndex}`;
  }
  if (!groups.length || entities.some((entry) => !memberships.has(entry.id))) {
    groups.push({
      id: ungrouped,
      name: "Ungrouped",
      color: "#7d9b8b",
      collapsed: false,
      locked: false,
    });
  }
  // Place entities around their primary real connection, independent of optional catalog groups.
  const primaryBroker = new Map<string, string>();
  for (const device of document.devices)
    if (device.connection_id)
      primaryBroker.set(device.id, device.connection_id);
  for (const stream of document.streams)
    if (stream.device_id && !primaryBroker.has(stream.device_id))
      primaryBroker.set(stream.device_id, stream.connection_id);
  const clusterIds = document.connections.map((entry) => entry.id);
  let unboundCluster = "system:layout:unbound";
  while (existingIds.has(unboundCluster)) unboundCluster += ":";
  if (document.devices.some((entry) => !primaryBroker.has(entry.id)))
    clusterIds.push(unboundCluster);
  const counts = new Map<string, number>();
  for (const entry of document.devices) {
    const broker = primaryBroker.get(entry.id) ?? unboundCluster;
    counts.set(broker, (counts.get(broker) ?? 0) + 1);
  }
  // Hidden standalone readings do not inflate structural cluster spacing.
  const centers = new Map<string, { x: number; z: number }>();
  const columns = Math.max(1, Math.ceil(Math.sqrt(clusterIds.length)));
  let rowZ = 0;
  for (let row = 0; row < clusterIds.length; row += columns) {
    const entries = clusterIds.slice(row, row + columns);
    const radii = entries.map(
      (id) => 6.5 + Math.sqrt(Math.max(0, (counts.get(id) ?? 0) - 1)) * 2.8,
    );
    const rowRadius = Math.max(...radii);
    let nextX = 0;
    entries.forEach((id, index) => {
      const radius = radii[index]!;
      centers.set(id, { x: nextX + radius, z: rowZ + rowRadius });
      nextX += radius * 2 + 3;
    });
    rowZ += rowRadius * 2 + 3;
  }
  const centerValues = [...centers.values()];
  const offsetX = centerValues.length
    ? (Math.min(...centerValues.map((point) => point.x)) +
        Math.max(...centerValues.map((point) => point.x))) /
      2
    : 0;
  const offsetZ = centerValues.length
    ? (Math.min(...centerValues.map((point) => point.z)) +
        Math.max(...centerValues.map((point) => point.z))) /
      2
    : 0;
  for (const point of centers.values()) {
    point.x -= offsetX;
    point.z -= offsetZ;
  }
  const nextSlot = new Map<string, number>();
  const entityPositions = new Map<string, { x: number; z: number }>();
  const satellite = (
    anchor: { x: number; z: number },
    key: string,
    radius: number,
    spacing: number,
    maximum = Infinity,
  ) => {
    const slot = nextSlot.get(key) ?? 0;
    nextSlot.set(key, slot + 1);
    const angle = slot * 2.399963229728653 + Math.PI / 5;
    const distance = Math.min(maximum, radius + Math.sqrt(slot) * spacing);
    return {
      x: anchor.x + Math.cos(angle) * distance,
      z: anchor.z + Math.sin(angle) * distance,
    };
  };
  const makeNode = (
    id: string,
    label: string,
    kind: SpatialNode["kind"],
    position: { x: number; z: number },
  ): SpatialNode => ({
    id,
    label,
    kind,
    groupId: memberships.get(id) ?? ungrouped,
    position,
    locked: false,
    unit: "",
    metric: label,
    baseRate: 0,
  });
  const nodes: SpatialNode[] = [];
  const edges: Topology["edges"] = [];
  for (const entry of document.connections) {
    nodes.push({
      ...makeNode(
        entry.id,
        entry.label,
        "broker",
        centers.get(entry.id) ?? { x: 0, z: 0 },
      ),
      system: {
        kind: "connection",
        id: entry.id,
        host: entry.host,
        protocol: entry.protocol,
      },
      metric: "Connection",
    });
  }
  for (const entry of document.devices) {
    const broker = primaryBroker.get(entry.id) ?? unboundCluster;
    const position = satellite(
      centers.get(broker) ?? { x: 0, z: 0 },
      broker,
      3.8,
      2.8,
    );
    entityPositions.set(entry.id, position);
    nodes.push({
      ...makeNode(entry.id, entry.label, "device", position),
      ...(entry.connection_id ? { brokerId: entry.connection_id } : {}),
      system: {
        kind: "device",
        id: entry.id,
        deviceKind: entry.kind,
        ...(entry.connection_id ? { connectionId: entry.connection_id } : {}),
      },
      metric: entry.kind,
    });
    if (entry.parent_id)
      edges.push({
        id: `parent:${entry.id}`,
        source: entry.id,
        target: entry.parent_id,
      });
    if (entry.connection_id)
      edges.push({
        id: `device-binding:${entry.id}`,
        source: entry.id,
        target: entry.connection_id,
      });
  }
  const bindingEdges = new Set(
    edges
      .filter((edge) => edge.id.startsWith("device-binding:"))
      .map((edge) => JSON.stringify([edge.source, edge.target])),
  );
  for (const entry of document.streams) {
    const anchor = entry.device_id
      ? entityPositions.get(entry.device_id)
      : centers.get(entry.connection_id);
    const position = satellite(
      anchor ?? { x: 0, z: 0 },
      entry.device_id ? `measurements:${entry.device_id}` : entry.connection_id,
      entry.device_id ? 1.5 : 3.8,
      entry.device_id ? 0.55 : 2.8,
      entry.device_id ? 2.6 : 4.5,
    );
    nodes.push({
      ...makeNode(entry.id, entry.label, "sensor", position),
      brokerId: entry.connection_id,
      unit: entry.unit ?? "",
      system: {
        kind: "stream",
        id: entry.id,
        connectionId: entry.connection_id,
        ...(entry.device_id ? { deviceId: entry.device_id } : {}),
        topic: entry.topic,
        ...(entry.payload_pointer !== undefined
          ? { payloadPointer: entry.payload_pointer }
          : {}),
        valueType: entry.value_type,
        category: entry.category,
        policy: entry.policy ?? document.default_policy,
      },
    });
    edges.push({
      id: `stream:${entry.id}`,
      source: entry.id,
      target: entry.device_id ?? entry.connection_id,
    });
    if (entry.device_id) {
      const key = JSON.stringify([entry.device_id, entry.connection_id]);
      if (!bindingEdges.has(key)) {
        bindingEdges.add(key);
        edges.push({
          id: `device-source:${entry.device_id}:${entry.connection_id}`,
          source: entry.device_id,
          target: entry.connection_id,
        });
      }
    }
  }
  const workspace = {
    ...createDefaultWorkspace(),
    groups,
    memberships: Object.fromEntries(
      nodes.map((node) => [node.id, node.groupId]),
    ),
  };
  const valueTypes = { number: 0, boolean: 0, text: 0, identifier: 0 };
  for (const entry of document.streams) valueTypes[entry.value_type] += 1;
  return {
    document,
    topology: { nodes, edges },
    workspace,
    groups,
    datasetKey: fingerprint(
      JSON.stringify(entities.map((entry) => entry.id).sort()),
    ),
    summary: {
      connections: document.connections.length,
      devices: document.devices.length,
      streams: document.streams.length,
      groups: document.groups.length,
      valueTypes,
    },
  };
}

/** Configuration owns membership and group names; the view owns camera and placement. */
export function reconcileSystemWorkspace(
  projection: SystemProjection,
  saved: SpatialWorkspace,
): SpatialWorkspace {
  const nodeIds = new Set(projection.topology.nodes.map((node) => node.id));
  const savedGroups = new Map(saved.groups.map((entry) => [entry.id, entry]));
  const filterNodes = <T>(map: Record<string, T>): Record<string, T> =>
    Object.fromEntries(Object.entries(map).filter(([id]) => nodeIds.has(id)));
  return {
    ...saved,
    positions: Object.fromEntries(
      projection.topology.nodes.map((node) => [
        node.id,
        workspaceValue(saved.positions, node.id) ?? node.position,
      ]),
    ),
    locks: filterNodes(saved.locks),
    ...(saved.personalGroups
      ? {
          personalGroups: saved.personalGroups.map((group) => ({
            ...group,
            memberIds: group.memberIds.filter((id) => nodeIds.has(id)),
          })),
        }
      : {}),
    memberships: { ...projection.workspace.memberships },
    groups: projection.groups.map((entry) => {
      const previous = savedGroups.get(entry.id);
      return {
        ...entry,
        ...(previous
          ? { collapsed: previous.collapsed, locked: previous.locked }
          : {}),
      };
    }),
  };
}
