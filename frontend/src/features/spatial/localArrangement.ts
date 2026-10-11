import { nodeVisualKind, nodeVisualScale } from "./sceneGeometry";
import type { Point, SpatialNode, SpatialWorkspace } from "./types";

export const TIDY_GRID_STEP = 1;
export const TIDY_MIN_SEPARATION = 2.4;
export const TIDY_MAX_MOVEMENT = 8;
const POSITION_LIMIT = 10_000;
const EPSILON = 1e-8;

type Unit = {
  id: string;
  members: SpatialNode[];
  origin: Point;
  radius: number;
  fixed: boolean;
  snapDistance: number;
  bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
};
const squaredDistance = (a: Point, b: Point) =>
  (a.x - b.x) ** 2 + (a.z - b.z) ** 2;
const snap = (point: Point): Point => ({
  x: Math.round(point.x),
  z: Math.round(point.z),
});
const key = (x: number, z: number) => `${x},${z}`;

// Rounding the origin can add half a grid diagonal to the search envelope.
const offsetLimit = Math.ceil(TIDY_MAX_MOVEMENT + Math.SQRT1_2);
const offsets: Point[] = [];
for (let x = -offsetLimit; x <= offsetLimit; x += 1) {
  for (let z = -offsetLimit; z <= offsetLimit; z += 1) {
    if (x * x + z * z <= (TIDY_MAX_MOVEMENT + Math.SQRT1_2) ** 2)
      offsets.push({ x, z });
  }
}
offsets.sort(
  (a, b) =>
    squaredDistance(a, { x: 0, z: 0 }) - squaredDistance(b, { x: 0, z: 0 }) ||
    a.x - b.x ||
    a.z - b.z,
);

/** Hash forbidden grid slots by footprint class; candidate checks are constant time. */
class ReservedSlots {
  private readonly slots = new Map<number, Set<string>>();
  constructor(radii: number[]) {
    for (const radius of radii) this.slots.set(radius, new Set());
  }
  occupy(point: Point, radius: number) {
    for (const [candidateRadius, slots] of this.slots) {
      const clearance = radius + candidateRadius;
      const limit = clearance * clearance - EPSILON;
      for (
        let x = Math.ceil(point.x - clearance);
        x <= Math.floor(point.x + clearance);
        x += 1
      ) {
        for (
          let z = Math.ceil(point.z - clearance);
          z <= Math.floor(point.z + clearance);
          z += 1
        ) {
          if ((x - point.x) ** 2 + (z - point.z) ** 2 < limit)
            slots.add(key(x, z));
        }
      }
    }
  }
  isFree(point: Point, radius: number) {
    return !this.slots.get(radius)?.has(key(point.x, point.z));
  }
}

function makeUnit(
  id: string,
  members: SpatialNode[],
  collapsed: boolean,
): Unit {
  const first = members[0]!;
  // Relative summation reduces centroid drift when a rigid group is translated.
  const origin = {
    x:
      first.position.x +
      members.reduce(
        (sum, node) => sum + node.position.x - first.position.x,
        0,
      ) /
        members.length,
    z:
      first.position.z +
      members.reduce(
        (sum, node) => sum + node.position.z - first.position.z,
        0,
      ) /
        members.length,
  };
  const visual: SpatialNode = collapsed
    ? {
        ...first,
        kind: "group",
        catalog: members.find((node) => node.kind === "charger")?.catalog,
        system: members.find((node) => node.kind === "device")?.system,
      }
    : first;
  // The enlarged device glyph has a 1.95-unit footprint plus 0.25 clearance.
  const radius = Math.max(
    TIDY_MIN_SEPARATION / 2,
    nodeVisualKind(visual) === "charger"
      ? 0.65 * nodeVisualScale(visual) + 0.25
      : 0,
  );
  const bounds = {
    minX: -Infinity,
    maxX: Infinity,
    minZ: -Infinity,
    maxZ: Infinity,
  };
  for (const node of members) {
    bounds.minX = Math.max(
      bounds.minX,
      origin.x - POSITION_LIMIT - node.position.x,
    );
    bounds.maxX = Math.min(
      bounds.maxX,
      origin.x + POSITION_LIMIT - node.position.x,
    );
    bounds.minZ = Math.max(
      bounds.minZ,
      origin.z - POSITION_LIMIT - node.position.z,
    );
    bounds.maxZ = Math.min(
      bounds.maxZ,
      origin.z + POSITION_LIMIT - node.position.z,
    );
  }
  const distance = squaredDistance(origin, snap(origin));
  return {
    id,
    members,
    origin,
    radius,
    fixed: members.some((node) => node.locked),
    snapDistance: distance < EPSILON ** 2 ? 0 : distance,
    bounds,
  };
}

function nearestSlot(unit: Unit, reserved: ReservedSlots): Point | undefined {
  const center = snap(unit.origin);
  const allowed = (point: Point) =>
    point.x >= unit.bounds.minX - EPSILON &&
    point.x <= unit.bounds.maxX + EPSILON &&
    point.z >= unit.bounds.minZ - EPSILON &&
    point.z <= unit.bounds.maxZ + EPSILON &&
    squaredDistance(point, unit.origin) <= TIDY_MAX_MOVEMENT ** 2 + EPSILON;
  if (allowed(center) && reserved.isFree(center, unit.radius)) return center;
  let best: Point | undefined;
  let bestDistance = Infinity;
  for (const offset of offsets) {
    const point = { x: center.x + offset.x, z: center.z + offset.z };
    const distance = squaredDistance(point, unit.origin);
    if (
      distance > bestDistance + EPSILON ||
      !allowed(point) ||
      !reserved.isFree(point, unit.radius)
    )
      continue;
    if (
      !best ||
      distance < bestDistance - EPSILON ||
      (Math.abs(distance - bestDistance) <= EPSILON &&
        (point.x < best.x || (point.x === best.x && point.z < best.z)))
    ) {
      best = point;
      bestDistance = distance;
    }
  }
  return best;
}

/** Tidy nearby positions atomically; a dense scene is never scattered to make room. */
export function tidyLocalPositions(
  nodes: SpatialNode[],
  workspace: SpatialWorkspace,
): SpatialWorkspace {
  const groups = new Map(workspace.groups.map((group) => [group.id, group]));
  const groupMembers = new Map<string, SpatialNode[]>();
  for (const node of nodes) {
    const members = groupMembers.get(node.groupId) ?? [];
    members.push(node);
    groupMembers.set(node.groupId, members);
  }
  const units: Unit[] = [];
  const handled = new Set<string>();
  for (const node of nodes) {
    if (groups.get(node.groupId)?.collapsed) {
      if (handled.has(node.groupId)) continue;
      handled.add(node.groupId);
      units.push(
        makeUnit(
          `group:${node.groupId}`,
          groupMembers.get(node.groupId)!,
          true,
        ),
      );
    } else units.push(makeUnit(node.id, [node], false));
  }
  if (
    units.some(
      (unit) =>
        !Number.isFinite(unit.origin.x) || !Number.isFinite(unit.origin.z),
    )
  )
    return workspace;
  const reserved = new ReservedSlots([
    ...new Set(units.map((unit) => unit.radius)),
  ]);
  const targets = new Map<string, Point>();
  for (const unit of units)
    if (unit.fixed) reserved.occupy(unit.origin, unit.radius);
  // Keep already tidy slots first, then prefer the smallest snap adjustment.
  const moving = units
    .filter((unit) => !unit.fixed)
    .sort(
      (a, b) =>
        a.snapDistance - b.snapDistance ||
        (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
    );
  let changed = false;
  for (const unit of moving) {
    const target = nearestSlot(unit, reserved);
    if (!target) return workspace;
    const delta = {
      x:
        Math.abs(target.x - unit.origin.x) <= EPSILON
          ? 0
          : target.x - unit.origin.x,
      z:
        Math.abs(target.z - unit.origin.z) <= EPSILON
          ? 0
          : target.z - unit.origin.z,
    };
    if (delta.x || delta.z) changed = true;
    targets.set(unit.id, delta);
    reserved.occupy(
      { x: unit.origin.x + delta.x, z: unit.origin.z + delta.z },
      unit.radius,
    );
  }
  if (!changed) return workspace;
  const positions = { ...workspace.positions };
  for (const unit of units) {
    const delta = targets.get(unit.id) ?? { x: 0, z: 0 };
    for (const node of unit.members)
      positions[node.id] = {
        x: node.position.x + delta.x,
        z: node.position.z + delta.z,
      };
  }
  return { ...workspace, positions };
}
