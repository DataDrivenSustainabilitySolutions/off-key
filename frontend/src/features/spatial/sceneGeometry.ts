import type { Point, SpatialNode } from "./types";

export type GroupBounds = {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
};

export function groupBounds(
  nodes: SpatialNode[],
  positions: ReadonlyMap<string, Point>,
) {
  const bounds = new Map<string, GroupBounds>();
  for (const node of nodes) {
    const position = positions.get(node.id) ?? node.position;
    const current = bounds.get(node.groupId);
    const radius = node.kind === "broker" ? 0.9 : 0.48;
    if (current) {
      current.minX = Math.min(current.minX, position.x - radius);
      current.maxX = Math.max(current.maxX, position.x + radius);
      current.minZ = Math.min(current.minZ, position.z - radius);
      current.maxZ = Math.max(current.maxZ, position.z + radius);
    } else {
      bounds.set(node.groupId, {
        minX: position.x - radius,
        maxX: position.x + radius,
        minZ: position.z - radius,
        maxZ: position.z + radius,
      });
    }
  }
  for (const bound of bounds.values()) {
    bound.minX -= 0.7;
    bound.maxX += 0.7;
    bound.minZ -= 0.7;
    bound.maxZ += 0.7;
  }
  return bounds;
}

/** Both lines and event pulses evaluate the same curve, even during a drag. */
export function curvePoint(
  source: Point,
  target: Point,
  progress: number,
  out: { x: number; y: number; z: number },
) {
  const t = Math.max(0, Math.min(1, progress));
  const inverse = 1 - t;
  const c1x = source.x + (target.x - source.x) * 0.52;
  const c2z = source.z + (target.z - source.z) * 0.48;
  out.x =
    inverse ** 3 * source.x +
    3 * inverse ** 2 * t * c1x +
    3 * inverse * t ** 2 * target.x +
    t ** 3 * target.x;
  out.y = 0.15 + Math.sin(Math.PI * t) * 0.08;
  out.z =
    inverse ** 3 * source.z +
    3 * inverse ** 2 * t * source.z +
    3 * inverse * t ** 2 * c2z +
    t ** 3 * target.z;
  return out;
}

/** Orthographic zoom does not move the near plane; large maps also need camera clearance. */
export function fitCameraDepth(bounds: GroupBounds, currentDistance: number) {
  const radius = Math.hypot(
    (bounds.maxX - bounds.minX) / 2,
    (bounds.maxZ - bounds.minZ) / 2,
    1.25,
  );
  const distance = Math.max(currentDistance, radius + 24);
  return { distance, far: Math.max(400, distance + radius + 48) };
}
