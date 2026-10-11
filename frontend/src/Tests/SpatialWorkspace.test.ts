import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  arrangeTopology,
  createDefaultWorkspace,
  createDemoTopology,
  moveGroup,
  moveNodes,
  resolveTopology,
} from "@/features/spatial/model";
import {
  loadWorkspace,
  parseWorkspace,
  saveWorkspace,
} from "@/features/spatial/workspace";
import type {
  SpatialNode,
  SpatialWorkspace,
  Topology,
} from "@/features/spatial/types";

const STORAGE_KEY = "spatial-workspace-test";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("spatial workspace persistence", () => {
  it("roundtrips camera, positions, locks, groups and named perspectives without saving telemetry", () => {
    const workspace = createDefaultWorkspace();
    workspace.positions["sensor-1"] = { x: 24, z: -8 };
    workspace.locks["sensor-1"] = true;
    workspace.memberships["sensor-1"] = "energy";
    workspace.camera.target = [4, 0, 2];
    workspace.groups[0]!.name = "Assembly";
    workspace.groups[0]!.color = "#1266aa";
    workspace.perspectives = [
      {
        id: "detail",
        name: "Assembly detail",
        camera: { position: [10, 20, 10], target: [4, 0, 2], zoom: 2 },
      },
    ];

    expect(
      saveWorkspace(STORAGE_KEY, {
        ...workspace,
        telemetry: { "sensor-1": [123, 456] },
      } as SpatialWorkspace),
    ).toBe(true);
    expect(loadWorkspace(STORAGE_KEY)).toEqual(workspace);
    expect(localStorage.getItem(STORAGE_KEY)).not.toContain("telemetry");
  });

  it.each([
    "not json",
    JSON.stringify({ ...createDefaultWorkspace(), version: 2 }),
    JSON.stringify({
      ...createDefaultWorkspace(),
      positions: { "sensor-1": { x: null, z: 0 } },
    }),
    JSON.stringify({
      ...createDefaultWorkspace(),
      camera: { position: [1, 2, 3], target: [0, 0, 0], zoom: -1 },
    }),
    JSON.stringify({
      ...createDefaultWorkspace(),
      memberships: { "sensor-1": "deleted-group" },
    }),
    JSON.stringify({
      ...createDefaultWorkspace(),
      groups: [
        { id: "g", name: "G", color: "red", collapsed: false, locked: false },
      ],
    }),
    `{"version":1,"positions":{"__proto__":{"x":1,"z":1}},"locks":{},"memberships":{},"groups":${JSON.stringify(createDefaultWorkspace().groups)},"camera":${JSON.stringify(createDefaultWorkspace().camera)},"perspectives":[]}`,
  ])(
    "recovers a default workspace from corrupt or incompatible browser state",
    (saved) => {
      localStorage.setItem(STORAGE_KEY, saved);
      expect(loadWorkspace(STORAGE_KEY)).toEqual(createDefaultWorkspace());
      expect(Object.prototype).not.toHaveProperty("x");
    },
  );

  it("rejects nonfinite and excessive input before writing storage", () => {
    const workspace = createDefaultWorkspace();
    for (const x of [Number.NaN, Number.POSITIVE_INFINITY, 10_001]) {
      expect(
        saveWorkspace(STORAGE_KEY, {
          ...workspace,
          positions: { "sensor-1": { x, z: 0 } },
        }),
      ).toBe(false);
    }
    expect(
      saveWorkspace(STORAGE_KEY, {
        ...workspace,
        groups: [{ ...workspace.groups[0]!, name: "x".repeat(81) }],
      }),
    ).toBe(false);
    localStorage.setItem(STORAGE_KEY, " ".repeat(1_000_001));
    expect(loadWorkspace(STORAGE_KEY)).toEqual(workspace);
  });

  it("keeps the interface usable when browser storage is disabled or full", () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("disabled");
    });
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(loadWorkspace(STORAGE_KEY)).toEqual(createDefaultWorkspace());
    expect(saveWorkspace(STORAGE_KEY, createDefaultWorkspace())).toBe(false);
  });

  it("imports a validated presentation snapshot without telemetry or unknown fields", () => {
    const workspace = createDefaultWorkspace();
    workspace.perspectives = [
      { id: "top-view", name: "Plan", camera: workspace.camera, view: "top" },
    ];
    expect(
      parseWorkspace(
        JSON.stringify({
          ...workspace,
          telemetry: { broker: [10, 20] },
          secrets: "ignored",
        }),
      ),
    ).toEqual(workspace);
    expect(parseWorkspace(JSON.stringify(workspace))).not.toHaveProperty(
      "telemetry",
    );
    expect(parseWorkspace(JSON.stringify(workspace))).not.toHaveProperty(
      "secrets",
    );
  });

  it("rejects incompatible imports atomically instead of partially restoring fields", () => {
    const workspace = createDefaultWorkspace();
    workspace.positions["sensor-1"] = { x: 5, z: 4 };
    expect(
      parseWorkspace(
        JSON.stringify({
          ...workspace,
          camera: { ...workspace.camera, position: [1, null, 3] },
        }),
      ),
    ).toBeUndefined();
    expect(
      parseWorkspace(
        JSON.stringify({
          ...workspace,
          perspectives: [
            {
              id: "bad-mode",
              name: "Bad",
              camera: workspace.camera,
              view: "sideways",
            },
          ],
        }),
      ),
    ).toBeUndefined();
    expect(parseWorkspace("broken json")).toBeUndefined();
    expect(parseWorkspace(" ".repeat(1_000_001))).toBeUndefined();
    expect(workspace.positions["sensor-1"]).toEqual({ x: 5, z: 4 });
  });
});

describe("spatial layout behavior", () => {
  it("preserves sensor identities and memberships as the demonstration scales", () => {
    const small = createDemoTopology(18);
    const large = createDemoTopology(300);
    expect(small.nodes.filter((node) => node.kind === "sensor")).toHaveLength(
      18,
    );
    for (const node of small.nodes) {
      expect(
        large.nodes.find((candidate) => candidate.id === node.id),
      ).toMatchObject({ groupId: node.groupId, kind: node.kind });
    }
    const ids = new Set(large.nodes.map((node) => node.id));
    expect(ids.size).toBe(large.nodes.length);
    expect(
      large.edges.every((edge) => ids.has(edge.source) && ids.has(edge.target)),
    ).toBe(true);
  });

  it("arranges deterministically around locked objects and locked groups without overlapping them", () => {
    const base = createDemoTopology();
    const workspace = createDefaultWorkspace();
    // Place a fixed sensor exactly where the workshop broker would otherwise go.
    workspace.positions["sensor-1"] = { ...base.nodes[0]!.position };
    workspace.locks["sensor-1"] = true;
    workspace.groups[1]!.locked = true;
    workspace.positions["sensor-2"] = { x: 40, z: 40 };
    const arranged = arrangeTopology(base, workspace);
    expect(arrangeTopology(base, workspace)).toEqual(arranged);
    expect(arranged.positions["sensor-1"]).toEqual(
      workspace.positions["sensor-1"],
    );
    expect(arranged.positions["sensor-2"]).toEqual(
      workspace.positions["sensor-2"],
    );
    expect(arranged.positions["broker-energy"]).toEqual(
      base.nodes[1]!.position,
    );
    const visible = resolveTopology(base, arranged).nodes;
    for (let a = 0; a < visible.length; a += 1) {
      for (let b = a + 1; b < visible.length; b += 1) {
        expect(
          Math.hypot(
            visible[a]!.position.x - visible[b]!.position.x,
            visible[a]!.position.z - visible[b]!.position.z,
          ),
        ).toBeGreaterThanOrEqual(2.4);
      }
    }
  });

  it("moves an unlocked group as a unit while retaining individually locked members", () => {
    const base = createDemoTopology();
    const workspace = createDefaultWorkspace();
    workspace.locks["sensor-1"] = true;
    const moved = moveGroup(base, workspace, "workshop", { x: 4, z: -3 });
    expect(moved.positions["sensor-1"]).toBeUndefined();
    expect(moved.positions["broker-workshop"]).toEqual({
      x: base.nodes[0]!.position.x + 4,
      z: base.nodes[0]!.position.z - 3,
    });
    workspace.groups[0]!.locked = true;
    expect(moveGroup(base, workspace, "workshop", { x: 4, z: -3 })).toBe(
      workspace,
    );
    expect(
      moveNodes(workspace, { "sensor-4": { x: 40, z: 40 } }).positions[
        "sensor-4"
      ],
    ).toBeUndefined();
  });

  it("uses visual membership without changing a sensor's broker connection", () => {
    const base = createDemoTopology();
    const workspace = createDefaultWorkspace();
    workspace.memberships["sensor-1"] = "energy";
    workspace.positions["sensor-1"] = { x: 1, z: 2 };
    const resolved = resolveTopology(base, workspace);
    expect(resolved.nodes.find((node) => node.id === "sensor-1")).toMatchObject(
      {
        groupId: "energy",
        brokerId: "broker-workshop",
        position: { x: 1, z: 2 },
      },
    );
    expect(
      resolved.edges.find((edge) => edge.source === "sensor-1")?.target,
    ).toBe("broker-workshop");
  });

  it("collapses groups to aggregate nodes and deduplicates links without dangling or internal edges", () => {
    const base = createDemoTopology();
    const workspace = createDefaultWorkspace();
    workspace.memberships["sensor-1"] = "energy";
    workspace.memberships["sensor-4"] = "energy";
    workspace.groups[0]!.collapsed = true;
    workspace.groups[1]!.collapsed = true;
    const resolved = resolveTopology(base, workspace);
    expect(
      resolved.nodes.find((node) => node.id === "group:energy")?.kind,
    ).toBe("group");
    expect(resolved.nodes.some((node) => node.id === "sensor-1")).toBe(false);
    expect(
      resolved.edges.filter(
        (edge) =>
          edge.source === "group:energy" && edge.target === "group:workshop",
      ),
    ).toHaveLength(1);
    const ids = new Set(resolved.nodes.map((node) => node.id));
    expect(
      resolved.edges.every(
        (edge) =>
          edge.source !== edge.target &&
          ids.has(edge.source) &&
          ids.has(edge.target),
      ),
    ).toBe(true);
  });
});

function node(
  id: string,
  x: number,
  z: number,
  groupId = "workshop",
  kind: SpatialNode["kind"] = "sensor",
): SpatialNode {
  return {
    id,
    label: id,
    kind,
    groupId,
    position: { x, z },
    locked: false,
    unit: "",
    metric: id,
    baseRate: 0,
    ...(kind === "device" ? { system: { kind: "device" as const, id } } : {}),
  };
}
const topology = (nodes: SpatialNode[]): Topology => ({ nodes, edges: [] });

describe("local position cleanup", () => {
  it("snaps objects near their current locations without changing spatial neighborhoods, metadata or group order", () => {
    const base = topology([
      node("a", 101.2, -40.3),
      node("b", 105.1, -40.7),
      node("c", -60.4, 35.4, "energy"),
    ]);
    const workspace = createDefaultWorkspace();
    const arranged = arrangeTopology(base, workspace);
    expect(arranged.positions.a).toEqual({ x: 101, z: -40 });
    expect(arranged.positions.b).toEqual({ x: 105, z: -41 });
    expect(arranged.positions.c).toEqual({ x: -60, z: 35 });
    expect(arranged.camera).toBe(workspace.camera);
    expect(arranged.groups).toBe(workspace.groups);
    expect(arranged.memberships).toBe(workspace.memberships);
    expect(
      arrangeTopology(
        { ...base, nodes: [...base.nodes].reverse() },
        { ...workspace, groups: [...workspace.groups].reverse() },
      ).positions,
    ).toEqual(arranged.positions);
    expect(arrangeTopology(base, arranged)).toBe(arranged);
  });

  it("keeps an already tidy neighbor's slot instead of moving it after another object snaps into it", () => {
    const base = topology([
      node("a-needs-snap", 0.6, 0),
      node("z-already-tidy", 3, 0),
    ]);
    const arranged = arrangeTopology(base, createDefaultWorkspace());
    expect(arranged.positions["z-already-tidy"]).toEqual({ x: 3, z: 0 });
    expect(arranged.positions["a-needs-snap"]).toEqual({ x: 0, z: 0 });
  });

  it("preserves off-grid pinned positions and locked groups while resolving nearby movable overlap", () => {
    const base = topology([
      node("pinned", 10.2, 10.4),
      node("movable", 10.1, 10.1),
      node("locked-group", 40.2, -60.4, "energy"),
    ]);
    const workspace = createDefaultWorkspace();
    workspace.locks.pinned = true;
    workspace.groups[1]!.locked = true;
    const arranged = arrangeTopology(base, workspace);
    expect(arranged.positions.pinned).toEqual(base.nodes[0]?.position);
    expect(arranged.positions["locked-group"]).toEqual(base.nodes[2]?.position);
    expect(
      Math.hypot(
        arranged.positions.movable!.x - 10.2,
        arranged.positions.movable!.z - 10.4,
      ),
    ).toBeGreaterThanOrEqual(2.4);
    expect(
      Math.hypot(
        arranged.positions.movable!.x - 10.1,
        arranged.positions.movable!.z - 10.1,
      ),
    ).toBeLessThanOrEqual(8);
  });

  it("translates collapsed device groups as rigid units with enough separation for their neutral footprint", () => {
    const members = (prefix: string, x: number, groupId: string) => [
      node(`${prefix}:device`, x, -8.2, groupId, "device"),
      node(`${prefix}:stream`, x + 1.5, -7.3, groupId),
      node(`${prefix}:broker`, x - 1.5, -9.1, groupId, "broker"),
    ];
    const base = topology([
      ...members("a", 20.2, "workshop"),
      ...members("b", 21.2, "energy"),
    ]);
    const workspace = createDefaultWorkspace();
    workspace.groups[0]!.collapsed = true;
    workspace.groups[1]!.collapsed = true;
    const arranged = arrangeTopology(base, workspace);
    for (const prefix of ["a", "b"]) {
      const original = base.nodes.find(
        (item) => item.id === `${prefix}:device`,
      )!;
      const translated = arranged.positions[original.id]!;
      const delta = {
        x: translated.x - original.position.x,
        z: translated.z - original.position.z,
      };
      for (const member of base.nodes.filter((item) =>
        item.id.startsWith(`${prefix}:`),
      )) {
        expect(arranged.positions[member.id]).toEqual({
          x: member.position.x + delta.x,
          z: member.position.z + delta.z,
        });
      }
      expect(Math.hypot(delta.x, delta.z)).toBeLessThanOrEqual(8);
    }
    const visible = resolveTopology(base, arranged).nodes;
    expect(
      Math.hypot(
        visible[0]!.position.x - visible[1]!.position.x,
        visible[0]!.position.z - visible[1]!.position.z,
      ),
    ).toBeGreaterThanOrEqual(2.4 - 1e-8);
    expect(arrangeTopology(base, arranged)).toBe(arranged);
  });

  it("keeps an entire collapsed group fixed when one of its members is individually pinned", () => {
    const base = topology([
      node("device", 8.2, -4.3, "workshop", "device"),
      node("pinned-member", 9.6, -3.4),
      node("nearby", 8.1, -4.1, "energy"),
    ]);
    const workspace = createDefaultWorkspace();
    workspace.groups[0]!.collapsed = true;
    workspace.locks["pinned-member"] = true;
    const arranged = arrangeTopology(base, workspace);
    expect(arranged.positions.device).toEqual(base.nodes[0]?.position);
    expect(arranged.positions["pinned-member"]).toEqual(
      base.nodes[1]?.position,
    );
    expect(arrangeTopology(base, arranged)).toBe(arranged);
  });

  it("leaves a scene intact when overlap cannot be resolved inside the small cleanup radius", () => {
    const base = topology(
      Array.from({ length: 4096 }, (_, index) =>
        node(`coincident:${index}`, 150.3, -80.4),
      ),
    );
    const workspace = createDefaultWorkspace();
    expect(arrangeTopology(base, workspace)).toBe(workspace);
    expect(workspace.positions).toEqual({});
    expect(arrangeTopology(base, workspace)).toBe(workspace);
  });

  it("tidies a distributed 4k-object scene locally and stays idempotent", () => {
    const base = topology(
      Array.from({ length: 4096 }, (_, index) =>
        node(
          `distributed:${index}`,
          1000.2 + (index % 64) * 3.2,
          2000.4 + Math.floor(index / 64) * 3.2,
        ),
      ),
    );
    const workspace = createDefaultWorkspace();
    const arranged = arrangeTopology(base, workspace);
    expect(arranged).not.toBe(workspace);
    for (const original of base.nodes) {
      const position = arranged.positions[original.id]!;
      expect(Number.isInteger(position.x) && Number.isInteger(position.z)).toBe(
        true,
      );
      expect(
        Math.hypot(
          position.x - original.position.x,
          position.z - original.position.z,
        ),
      ).toBeLessThanOrEqual(8);
    }
    expect(arrangeTopology(base, arranged)).toBe(arranged);
  });

  it("retains valid saved coordinates at the workspace boundary", () => {
    const base = topology([
      node("edge-a", 10_000, 9999.9),
      node("edge-b", 9999.5, 9999.8),
    ]);
    const arranged = arrangeTopology(base, createDefaultWorkspace());
    expect(
      Object.values(arranged.positions).every(
        (point) => Math.abs(point.x) <= 10_000 && Math.abs(point.z) <= 10_000,
      ),
    ).toBe(true);
    expect(saveWorkspace(STORAGE_KEY, arranged)).toBe(true);
  });
});
