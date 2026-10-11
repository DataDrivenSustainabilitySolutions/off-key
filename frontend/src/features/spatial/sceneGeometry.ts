import type { Point, SpatialNode } from "./types";

export type NodeVisualKind =
  "broker" | "sensor" | "group" | "charger" | "device";
export const MAX_NODE_HEIGHT = 1.7;

/** Generic entities stay neutral; only the legacy charger preview uses a charger silhouette. */
export function nodeVisualKind(node: SpatialNode): NodeVisualKind {
  if (
    node.kind === "device" ||
    (node.kind === "group" && node.system?.kind === "device")
  )
    return "device";
  return node.kind === "group" && node.catalog?.chargerId
    ? "charger"
    : node.kind;
}

export function nodeVisualScale(node: SpatialNode): number {
  return node.kind === "group" && node.catalog?.chargerId ? 3 : 1;
}

export function nodeVisualHeight(node: SpatialNode): number {
  return nodeVisualKind(node) === "charger"
    ? 0.09 + (MAX_NODE_HEIGHT - 0.09) * nodeVisualScale(node)
    : node.kind === "broker"
      ? 0.85
      : nodeVisualKind(node) === "device"
        ? 0.64
        : 0.6;
}

/** Compact fleet labels retain the beginning of the name; focus reveals it in full. */
export function sceneNodeLabel(node: SpatialNode, focused = false): string {
  if (
    focused ||
    !["charger", "device", "broker"].includes(nodeVisualKind(node))
  )
    return node.label;
  return node.label.length > 14
    ? `${node.label.slice(0, 14).trimEnd()}…`
    : node.label;
}

export type ScreenLabel = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  priority: number;
};

/** Rectangles use cached text estimates; no DOM measurements are needed per frame. */
export function visibleSceneLabels(
  labels: readonly ScreenLabel[],
  gap = 6,
): Set<string> {
  const accepted: ScreenLabel[] = [];
  const visible = new Set<string>();
  for (const label of [...labels].sort((a, b) => b.priority - a.priority)) {
    if (accepted.length >= 40) continue;
    const overlaps = accepted.some(
      (other) =>
        label.x < other.x + other.width + gap &&
        label.x + label.width + gap > other.x &&
        label.y < other.y + other.height + gap &&
        label.y + label.height + gap > other.y,
    );
    // Hovered and selected identities remain discoverable even when the map is dense.
    if (overlaps && !label.priority) continue;
    accepted.push(label);
    visible.add(label.id);
  }
  return visible;
}

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
    const kind = nodeVisualKind(node);
    const radius =
      (kind === "broker"
        ? 0.9
        : kind === "charger"
          ? 0.65
          : kind === "device"
            ? 0.8
            : 0.48) * nodeVisualScale(node);
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
export function fitCameraDepth(
  bounds: GroupBounds,
  currentDistance: number,
  height = MAX_NODE_HEIGHT,
) {
  const radius = Math.hypot(
    (bounds.maxX - bounds.minX) / 2,
    (bounds.maxZ - bounds.minZ) / 2,
    height,
  );
  const distance = Math.max(currentDistance, radius + 24);
  return { distance, far: Math.max(400, distance + radius + 48) };
}
