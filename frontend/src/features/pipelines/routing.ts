import { Position, type Node, type XYPosition } from "@xyflow/react";
import { getSmartEdge, pathfindingJumpPointNoDiagonal, svgDrawSmoothStepLinePath } from "@tisoap/react-flow-smart-edge";
import { edgeId } from "./semantics";

export type RoutingBox = { id: string; x: number; y: number; width: number; height: number };
export type ConnectionRoute = { path: string; points: XYPosition[]; blocked: boolean };
type Connection = { source: string; target: string };

const CLEARANCE = 8;
const CORNER_RADIUS = 5;
const MAX_GRID_CELLS = 131_072;
const drawPath = svgDrawSmoothStepLinePath({ borderRadius: CORNER_RADIUS });
const EPSILON = 0.001;

function crossesBox(a: XYPosition, b: XYPosition, box: RoutingBox, padding = 0) {
  const left = box.x - padding + EPSILON;
  const right = box.x + box.width + padding - EPSILON;
  const top = box.y - padding + EPSILON;
  const bottom = box.y + box.height + padding - EPSILON;
  if (Math.abs(a.y - b.y) < EPSILON)
    return a.y > top && a.y < bottom && Math.max(a.x, b.x) > left && Math.min(a.x, b.x) < right;
  if (Math.abs(a.x - b.x) < EPSILON)
    return a.x > left && a.x < right && Math.max(a.y, b.y) > top && Math.min(a.y, b.y) < bottom;
  return true;
}

/** Check the router's actual output, including the tunnels it carves at ports. */
function clearPath(points: XYPosition[], boxes: RoutingBox[], edge: Connection) {
  const first = points[0]!;
  const last = points[points.length - 1]!;
  if (points.length < 2 || points[1]!.x < first.x || points[points.length - 2]!.x > last.x) return false;
  return points.slice(1).every((b, index) => {
    const a = points[index]!;
    return boxes.every((box) => {
      const sourceExit = box.id === edge.source && a.y === first.y && b.y === first.y
        && Math.min(a.x, b.x) >= first.x;
      const targetEntry = box.id === edge.target && a.y === last.y && b.y === last.y
        && Math.max(a.x, b.x) <= last.x;
      return !crossesBox(a, b, box, sourceExit || targetEntry ? 0 : CORNER_RADIUS + 2);
    });
  });
}

function compact(points: XYPosition[]) {
  const result: XYPosition[] = [];
  for (const point of points) {
    const last = result[result.length - 1];
    if (last && last.x === point.x && last.y === point.y) continue;
    const previous = result[result.length - 2];
    if (previous && last && ((previous.x === last.x && last.x === point.x)
      || (previous.y === last.y && last.y === point.y))) result.pop();
    result.push(point);
  }
  return result;
}

type Stretch = { from: number; to: number };

/** Parts of [from, to] that no listed interval covers. */
function uncovered(from: number, to: number, covered: Stretch[]) {
  const free: Stretch[] = [];
  let cursor = from;
  for (const stretch of [...covered].sort((left, right) => left.from - right.from)) {
    if (stretch.from > cursor) free.push({ from: cursor, to: Math.min(stretch.from, to) });
    cursor = Math.max(cursor, stretch.to);
    if (cursor >= to) break;
  }
  if (cursor < to) free.push({ from: cursor, to });
  return free;
}

/** Shortest horizontal stretch that holds a handle clear of the ports and the arrowhead. */
const MIN_HANDLE_STRETCH = 40;
/** Shorter free stretches sit where links part, too close to the junction for a handle. */
const MIN_FREE_STRETCH = 32;

/** Where each routed link carries its handle: the middle of its longest horizontal
 * stretch that no other link runs along, so a handle never sits on a shared trunk
 * where it would be ambiguous. Vertical stretches are used when no horizontal one is
 * long enough, and the longest segment when the link shares every stretch. */
export function routeHandles(routes: Map<string, ConnectionRoute>) {
  type Segment = { id: string; horizontal: boolean; line: number; from: number; to: number };
  type Candidate = { horizontal: boolean; length: number; point: XYPosition };
  // Links run on a shared grid, so collinear segments have identical coordinates.
  const lines = new Map<string, Segment[]>();
  const segments: Segment[] = [];
  for (const [id, route] of routes)
    for (const [index, end] of route.points.slice(1).entries()) {
      const start = route.points[index]!;
      const horizontal = Math.abs(start.y - end.y) < EPSILON;
      if (!horizontal && Math.abs(start.x - end.x) >= EPSILON) continue;
      const axis = horizontal ? "x" : "y";
      const segment = {
        id, horizontal, line: horizontal ? start.y : start.x,
        from: Math.min(start[axis], end[axis]), to: Math.max(start[axis], end[axis]),
      };
      const key = `${horizontal ? "h" : "v"}${Math.round(segment.line / EPSILON)}`;
      lines.set(key, [...(lines.get(key) ?? []), segment]);
      segments.push(segment);
    }
  const rank = (candidate: Candidate) => (candidate.horizontal && candidate.length >= MIN_HANDLE_STRETCH ? 1 : 0);
  const better = (candidate: Candidate, best?: Candidate) => !best || rank(candidate) > rank(best)
    || (rank(candidate) === rank(best) && candidate.length > best.length);
  const best = new Map<string, Candidate>();
  const fallback = new Map<string, Candidate>();
  for (const segment of segments) {
    const { id, horizontal, line, from, to } = segment;
    const at = (middle: number) => (horizontal ? { x: middle, y: line } : { x: line, y: middle });
    const whole = { horizontal, length: to - from, point: at((from + to) / 2) };
    if (better(whole, fallback.get(id))) fallback.set(id, whole);
    const covered = lines.get(`${horizontal ? "h" : "v"}${Math.round(line / EPSILON)}`)!
      .filter((other) => other.id !== id);
    for (const stretch of uncovered(from, to, covered)) {
      if (stretch.to - stretch.from < MIN_FREE_STRETCH) continue;
      const candidate = { horizontal, length: stretch.to - stretch.from, point: at((stretch.from + stretch.to) / 2) };
      if (better(candidate, best.get(id))) best.set(id, candidate);
    }
  }
  const handles = new Map<string, XYPosition>();
  // A link that shares every stretch still needs a handle; its longest segment is the clearest.
  for (const [id, route] of routes) {
    const chosen = route.blocked ? undefined : best.get(id) ?? fallback.get(id);
    if (chosen) handles.set(id, chosen.point);
  }
  return handles;
}

/** Derived canvas geometry only: bends never become saved or executable state. */
export function routeConnections(
  boxes: RoutingBox[],
  edges: Connection[],
  /** During a drag, reuse settled routes of links that do not touch a moving component. */
  partial?: { previous: Map<string, ConnectionRoute>; changed: Set<string> },
) {
  const byId = new Map(boxes.map((box) => [box.id, box]));
  const nodes: Node[] = boxes.map(({ id, x, y, width, height }) => ({
    id, position: { x, y }, measured: { width, height }, data: {},
  }));
  // Saved positions are unbounded. Bound allocations even for a very sparse canvas.
  const width = Math.max(...boxes.map((box) => box.x + box.width)) - Math.min(...boxes.map((box) => box.x)) + 128;
  const height = Math.max(...boxes.map((box) => box.y + box.height)) - Math.min(...boxes.map((box) => box.y)) + 128;
  const gridRatio = Math.max(8, Math.ceil(Math.sqrt(width * height / MAX_GRID_CELLS)));
  const gridSizes = gridRatio === 8 && width * height / 16 <= MAX_GRID_CELLS ? [8, 4] : [gridRatio];
  const routes = new Map<string, ConnectionRoute>();
  const moving = partial ? boxes.filter((box) => partial.changed.has(box.id)) : [];
  for (const edge of edges) {
    const sourceBox = byId.get(edge.source);
    const targetBox = byId.get(edge.target);
    if (!sourceBox || !targetBox) continue;
    const settled = partial && !partial.changed.has(edge.source) && !partial.changed.has(edge.target)
      ? partial.previous.get(edgeId(edge)) : undefined;
    // A moving card can land on an unrelated link, which then has to reroute as well.
    if (settled && !settled.blocked && clearPath(settled.points, moving, edge)) {
      routes.set(edgeId(edge), settled);
      continue;
    }
    const source = { x: sourceBox.x + sourceBox.width, y: sourceBox.y + sourceBox.height / 2 };
    const target = { x: targetBox.x, y: targetBox.y + targetBox.height / 2 };
    const direct = [source, target];
    let points = source.y === target.y && source.x < target.x && clearPath(direct, boxes, edge) ? direct : undefined;
    if (!points) {
      // Most routes use the coarser grid; retry narrow corridors at finer resolution.
      for (const ratio of gridSizes) {
        const result = getSmartEdge({
          sourceX: source.x, sourceY: source.y, targetX: target.x, targetY: target.y,
          sourcePosition: Position.Right, targetPosition: Position.Left, nodes,
          options: { nodePadding: CLEARANCE, gridRatio: ratio, generatePath: pathfindingJumpPointNoDiagonal },
        });
        if (result instanceof Error) continue;
        const cells = result.points.map(([x, y]) => ({ x: x!, y: y! }));
        // Ports within one routing cell of each other in height come back as a single
        // row at the source's height, which would slant into the target. Step at the
        // first cell instead, as a route across two rows does.
        const level = cells.every((cell) => cell.y === source.y) && source.y !== target.y;
        const candidate = compact(level
          ? [source, cells[0]!, ...cells.map((cell) => ({ x: cell.x, y: target.y })), target]
          : [source, ...cells, target]);
        if (clearPath(candidate, boxes, edge)) { points = candidate; break; }
      }
    }
    routes.set(edgeId(edge), points ? {
      path: drawPath(source, target, points.slice(1, -1).map(({ x, y }) => [x, y])), points, blocked: false,
    } : {
      // A physically blocked port has no safe full route. Keep its ends identifiable.
      path: `M ${source.x},${source.y} L ${source.x + 14},${source.y} M ${target.x - 14},${target.y} L ${target.x},${target.y}`,
      points: [], blocked: true,
    });
  }
  return routes;
}
