import type {
  CameraPose,
  Point,
  SpatialNode,
  SpatialWorkspace,
  Topology,
} from "./types";
import { tidyLocalPositions } from "./localArrangement";

export const DEFAULT_CAMERA: CameraPose = {
  position: [22, 28, 30],
  target: [0, 0, 1],
  zoom: 1,
};

const GROUP_IDS = ["workshop", "energy", "environment"] as const;
const SPACING = 3.2;

/** Configuration IDs may match ordinary Object.prototype names. */
export function workspaceValue<T>(
  values: Record<string, T>,
  id: string,
): T | undefined {
  return Object.prototype.hasOwnProperty.call(values, id)
    ? values[id]
    : undefined;
}

export function createDefaultWorkspace(): SpatialWorkspace {
  return {
    version: 1,
    layoutMode: "automatic",
    positions: {},
    locks: {},
    memberships: {},
    groups: [
      {
        id: "workshop",
        name: "Workshop",
        color: "#0e8174",
        collapsed: false,
        locked: false,
      },
      {
        id: "energy",
        name: "Energy",
        color: "#ca8a25",
        collapsed: false,
        locked: false,
      },
      {
        id: "environment",
        name: "Environment",
        color: "#7561b7",
        collapsed: false,
        locked: false,
      },
    ],
    camera: {
      ...DEFAULT_CAMERA,
      position: [...DEFAULT_CAMERA.position],
      target: [...DEFAULT_CAMERA.target],
    },
    perspectives: [],
  };
}

const METRICS = [
  ["Temperature", "°C", 0.8],
  ["Humidity", "%", 0.35],
  ["CO₂", "ppm", 0.55],
  ["Voltage", "V", 2.5],
  ["Current", "A", 1.5],
  ["Power", "kW", 3.8],
] as const;

/** Synthetic IDs never contain real broker identities or credentials. */
export function createDemoTopology(sensorCount = 18): Topology {
  const count = Number.isFinite(sensorCount)
    ? Math.max(0, Math.min(3000, Math.floor(sensorCount)))
    : 18;
  const perGroup = Math.ceil(count / GROUP_IDS.length);
  const columns = Math.max(3, Math.ceil(Math.sqrt(perGroup)));
  const groupWidth = columns * SPACING + 1.4;
  const nodes: SpatialNode[] = GROUP_IDS.map((id, index) => ({
    id: `broker-${id}`,
    label: `${id[0]?.toUpperCase()}${id.slice(1)} broker`,
    kind: "broker",
    groupId: id,
    position: { x: (index - 1) * groupWidth, z: -3.5 },
    locked: false,
    unit: "msg/s",
    metric: "Throughput",
    baseRate: 0,
  }));
  const edges: Topology["edges"] = [];
  for (let index = 0; index < count; index += 1) {
    const groupIndex = index % GROUP_IDS.length;
    const groupId = GROUP_IDS[groupIndex]!;
    const localIndex = Math.floor(index / GROUP_IDS.length);
    const metric = METRICS[(localIndex + groupIndex * 2) % METRICS.length]!;
    const id = `sensor-${index + 1}`;
    nodes.push({
      id,
      label: `${metric[0]} ${String(localIndex + 1).padStart(2, "0")}`,
      kind: "sensor",
      brokerId: `broker-${groupId}`,
      groupId,
      position: {
        x:
          (groupIndex - 1) * groupWidth +
          ((localIndex % columns) - (columns - 1) / 2) * SPACING,
        z: 1 + Math.floor(localIndex / columns) * SPACING,
      },
      locked: false,
      unit: metric[1],
      metric: metric[0],
      baseRate: metric[2] + (localIndex % 3) * 0.08,
    });
    nodes[groupIndex]!.baseRate += metric[2] + (localIndex % 3) * 0.08;
    edges.push({ id: `edge-${id}`, source: id, target: `broker-${groupId}` });
  }
  return { nodes, edges };
}

function effectiveNodes(
  base: Topology,
  workspace: SpatialWorkspace,
): SpatialNode[] {
  const groups = new Map(workspace.groups.map((group) => [group.id, group]));
  return base.nodes.map((node) => {
    const savedGroup = workspaceValue(workspace.memberships, node.id);
    const groupId =
      savedGroup && groups.has(savedGroup) ? savedGroup : node.groupId;
    return {
      ...node,
      groupId,
      position: workspaceValue(workspace.positions, node.id) ?? node.position,
      locked:
        (workspaceValue(workspace.locks, node.id) ?? node.locked) ||
        (groups.get(groupId)?.locked ?? false),
    };
  });
}

export function resolveTopology(
  base: Topology,
  workspace: SpatialWorkspace,
): Topology {
  const nodes = effectiveNodes(base, workspace);
  const hiddenToGroup = new Map<string, string>();
  const visible = nodes.filter(
    (node) =>
      !workspace.groups.some(
        (group) => group.id === node.groupId && group.collapsed,
      ),
  );
  for (const group of workspace.groups) {
    if (!group.collapsed) continue;
    const members = nodes.filter((node) => node.groupId === group.id);
    if (!members.length) continue;
    const id = `group:${group.id}`;
    for (const member of members) hiddenToGroup.set(member.id, id);
    const centroid = members.reduce(
      (point, node) => ({
        x: point.x + node.position.x,
        z: point.z + node.position.z,
      }),
      { x: 0, z: 0 },
    );
    visible.push({
      id,
      label: group.name,
      kind: "group",
      catalog: members.find((node) => node.kind === "charger")?.catalog,
      system: members.find((node) => node.kind === "device")?.system,
      groupId: group.id,
      position: {
        x: centroid.x / members.length,
        z: centroid.z / members.length,
      },
      locked: group.locked,
      unit: "msg/s",
      metric: `${members.length} objects`,
      baseRate: members
        .filter((node) => node.kind === "sensor")
        .reduce((sum, node) => sum + node.baseRate, 0),
    });
  }
  const visibleIds = new Set(visible.map((node) => node.id));
  const seen = new Set<string>();
  const edges: Topology["edges"] = [];
  for (const edge of base.edges) {
    const source = hiddenToGroup.get(edge.source) ?? edge.source;
    const target = hiddenToGroup.get(edge.target) ?? edge.target;
    const id = `${source}→${target}`;
    if (
      source === target ||
      !visibleIds.has(source) ||
      !visibleIds.has(target) ||
      seen.has(id)
    )
      continue;
    seen.add(id);
    edges.push({ ...edge, id, source, target });
  }
  return { nodes: visible, edges };
}

/** Local, Finder-like cleanup preserves neighborhoods and rigid collapsed groups. */
export function arrangeTopology(
  base: Topology,
  workspace: SpatialWorkspace,
): SpatialWorkspace {
  return tidyLocalPositions(effectiveNodes(base, workspace), workspace);
}

function inferredGroup(id: string): string | undefined {
  if (id.startsWith("broker-")) return id.slice("broker-".length);
  const number = /^sensor-(\d+)$/.exec(id)?.[1];
  return number
    ? GROUP_IDS[(Number(number) - 1) % GROUP_IDS.length]
    : undefined;
}

export function moveNodes(
  workspace: SpatialWorkspace,
  changes: Record<string, Point>,
): SpatialWorkspace {
  const positions = { ...workspace.positions };
  for (const [id, point] of Object.entries(changes)) {
    const groupId =
      workspaceValue(workspace.memberships, id) ?? inferredGroup(id);
    const group = workspace.groups.find((item) => item.id === groupId);
    if (
      !workspaceValue(workspace.locks, id) &&
      !group?.locked &&
      Number.isFinite(point.x) &&
      Number.isFinite(point.z)
    )
      positions[id] = point;
  }
  return { ...workspace, positions };
}

export function moveGroup(
  topology: Topology,
  workspace: SpatialWorkspace,
  groupId: string,
  delta: Point,
): SpatialWorkspace {
  if (
    workspace.groups.find((group) => group.id === groupId)?.locked ||
    !Number.isFinite(delta.x) ||
    !Number.isFinite(delta.z)
  )
    return workspace;
  const changes: Record<string, Point> = {};
  for (const node of effectiveNodes(topology, workspace)) {
    if (node.groupId === groupId && !node.locked)
      changes[node.id] = {
        x: node.position.x + delta.x,
        z: node.position.z + delta.z,
      };
  }
  return moveNodes(workspace, changes);
}
