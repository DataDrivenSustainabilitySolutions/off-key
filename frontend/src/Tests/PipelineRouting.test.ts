// @vitest-environment node
import { describe, expect, it } from "vitest";
import { routeConnections, type ConnectionRoute, type RoutingBox } from "@/features/pipelines/routing";
import { edgeId, NODE_SIZE } from "@/features/pipelines/semantics";

const box = (id: string, x: number, y: number): RoutingBox => ({ id, x, y, ...NODE_SIZE });
const connection = { source: "source", target: "target" };
const route = (boxes: RoutingBox[]) => routeConnections(boxes, [connection]).get(edgeId(connection))!;

/** Check geometric behavior independently of the router's grid or SVG formatter. */
function expectClear(result: ConnectionRoute, boxes: RoutingBox[]) {
  expect(result.blocked).toBe(false);
  expect(result.points.length).toBeGreaterThanOrEqual(2);
  const source = boxes.find((node) => node.id === "source")!;
  const target = boxes.find((node) => node.id === "target")!;
  expect(result.points[0]).toEqual({ x: source.x + source.width, y: source.y + source.height / 2 });
  expect(result.points[result.points.length - 1]).toEqual({ x: target.x, y: target.y + target.height / 2 });
  for (let index = 1; index < result.points.length; index++) {
    const a = result.points[index - 1]!;
    const b = result.points[index]!;
    expect(a.x === b.x || a.y === b.y).toBe(true);
    for (const node of boxes) {
      // Intersecting either box interior is forbidden, including the endpoint boxes.
      const horizontal = a.y === b.y && a.y > node.y && a.y < node.y + node.height
        && Math.max(a.x, b.x) > node.x && Math.min(a.x, b.x) < node.x + node.width;
      const vertical = a.x === b.x && a.x > node.x && a.x < node.x + node.width
        && Math.max(a.y, b.y) > node.y && Math.min(a.y, b.y) < node.y + node.height;
      expect(horizontal || vertical, `Segment intersects ${node.id}`).toBe(false);
    }
  }
}

describe("pipeline obstacle routing", () => {
  it("keeps a clear aligned connection direct", () => {
    const boxes = [box("source", 0, 0), box("target", 320, 0)];
    const result = route(boxes);
    expectClear(result, boxes);
    expect(result.points).toHaveLength(2);
  });

  it("bends around an unrelated box and returns to a direct route when it moves", () => {
    const boxes = [box("source", 0, 0), box("target", 640, 0), box("obstacle", 320, -36)];
    const before = structuredClone(boxes);
    const result = route(boxes);
    expectClear(result, boxes);
    expect(result.points.length).toBeGreaterThan(2);
    expect(route(boxes)).toEqual(result);
    expect(boxes).toEqual(before);
    boxes[2]!.y = 250;
    expectClear(route(boxes), boxes);
    expect(route(boxes).points).toHaveLength(2);
  });

  it.each([
    [0, -240], [-320, 0], [-320, 160], [0, 240], [320, 240], [320, -240],
  ])("routes when the target moves to (%s, %s)", (x, y) => {
    const boxes = [box("source", 0, 0), box("target", x, y)];
    expectClear(route(boxes), boxes);
  });

  it("keeps fractional unsnapped positions attached without diagonal segments", () => {
    const boxes = [box("source", 52.3, 12.8), box("target", -350.4, 180.6), box("obstacle", -60, 220)];
    expectClear(route(boxes), boxes);
  });

  it("identifies a blocked port instead of drawing through an overlapping box", () => {
    const result = route([box("source", 0, 0), box("target", 100, 0)]);
    expect(result.blocked).toBe(true);
    expect(result.points).toEqual([]);
    expect(result.path.match(/M /g)).toHaveLength(2);
  });

  it("routes 128 connections across a 64-box scene", () => {
    const boxes = Array.from({ length: 64 }, (_, index) => box(String(index), index % 8 * 320, Math.floor(index / 8) * 240));
    const edges = [1, 2, 3].flatMap((stride) => boxes.slice(stride).map((target, index) => ({ source: String(index), target: target.id }))).slice(0, 128);
    const result = routeConnections(boxes, edges);
    expect(result.size).toBe(128);
    expect([...result.values()].filter((item) => item.blocked)).toHaveLength(0);
  });

  it("bounds routing allocations for extremely sparse saved coordinates", () => {
    const boxes = [box("source", -1_000_000, -1_000_000), box("target", 1_000_000, 1_000_000)];
    const result = route(boxes);
    expect(result.path).not.toMatch(/NaN|Infinity/);
    if (!result.blocked) expectClear(result, boxes);
  });

  it("routes the existing tightly packed maximum-graph layout", () => {
    const boxes = Array.from({ length: 64 }, (_, index) => box(String(index), index % 8 * 250, Math.floor(index / 8) * 150));
    const ids = ["0", ...boxes.slice(4).map((node) => node.id), "1", "2", "3"];
    const edges = ids.slice(1).map((target, index) => ({ source: ids[index]!, target }));
    const result = routeConnections(boxes, edges);
    expect([...result.values()].filter((item) => item.blocked)).toHaveLength(0);
  });
});
