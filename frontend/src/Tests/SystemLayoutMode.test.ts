import { describe, expect, it } from "vitest";
import {
  createDefaultWorkspace,
  resolveTopology,
} from "@/features/spatial/model";
import {
  loadWorkspace,
  parseWorkspace,
  saveWorkspace,
} from "@/features/spatial/workspace";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import { automaticSystemLayout } from "@/features/spatial/systemSceneView";
import type { SpatialWorkspace } from "@/features/spatial/types";

function fixture() {
  const system = createEmptySystem("Automatic system");
  system.connections = [
    {
      id: "broker",
      label: "Broker",
      protocol: "mqtt",
      host: "source.example.test",
      port: 1883,
      transport: "tcp",
      tls: false,
    },
  ];
  system.devices = [
    { id: "parent", label: "Parent", kind: "machine", connection_id: "broker" },
    { id: "child", label: "Child", kind: "component", parent_id: "parent" },
    {
      id: "sibling",
      label: "Sibling",
      kind: "machine",
      connection_id: "broker",
    },
  ];
  system.streams = [
    { id: "parent-reading", device_id: "parent" },
    { id: "child-reading", device_id: "child" },
    { id: "independent-pin", device_id: "child" },
    { id: "sibling-reading", device_id: "sibling" },
    { id: "standalone" },
  ].map((stream) => ({
    ...stream,
    label: stream.id,
    connection_id: "broker",
    topic: `lab/${stream.id}`,
    value_type: "number",
    category: "Measurements",
  }));
  system.groups = [
    { id: "assembly", label: "Assembly", member_ids: ["parent", "child"] },
  ];
  return { system, ...projectSystemDocument(system) };
}

const position = (projection: ReturnType<typeof fixture>, id: string) =>
  projection.topology.nodes.find((node) => node.id === id)!.position;

describe("legacy placement format compatibility", () => {
  it("starts new views in automatic mode and roundtrips either explicit mode", () => {
    expect(createDefaultWorkspace().layoutMode).toBe("automatic");
    for (const layoutMode of ["automatic", "manual"] as const) {
      const workspace = { ...createDefaultWorkspace(), layoutMode };
      expect(parseWorkspace(JSON.stringify(workspace))).toEqual(workspace);
      expect(saveWorkspace(`layout-mode:${layoutMode}`, workspace)).toBe(true);
      expect(loadWorkspace(`layout-mode:${layoutMode}`).layoutMode).toBe(
        layoutMode,
      );
    }
  });

  it("preserves legacy placement when an older saved view has no layout mode", () => {
    const legacy = createDefaultWorkspace();
    delete legacy.layoutMode;
    legacy.positions.parent = { x: 83, z: -42 };
    const parsed = parseWorkspace(JSON.stringify(legacy))!;
    expect(parsed).toEqual(legacy);
    expect(
      resolveTopology(fixture().topology, parsed).nodes.find(
        (node) => node.id === "parent",
      )?.position,
    ).toEqual({ x: 83, z: -42 });
  });

  it.each(["grid", "", true, null, 2, {}])(
    "rejects an invalid layout mode %j atomically",
    (layoutMode) => {
      const invalid = { ...createDefaultWorkspace(), layoutMode };
      expect(parseWorkspace(JSON.stringify(invalid))).toBeUndefined();
      expect(
        saveWorkspace("layout-mode:invalid", invalid as SpatialWorkspace),
      ).toBe(false);
    },
  );
});

describe("automatic-only configured system placement", () => {
  it.each([undefined, "manual", "automatic"] as const)(
    "ignores saved positions and pins for a configured view with legacy mode %s",
    (layoutMode) => {
      const projected = fixture();
      const saved: SpatialWorkspace = {
        ...projected.workspace,
        layoutMode,
        positions: {
          parent: { x: 83, z: -42 },
          "parent-reading": { x: 90, z: 9 },
          broker: { x: -50, z: 50 },
        },
        locks: { parent: true, "parent-reading": true, broker: true },
        groups: projected.workspace.groups.map((group) => ({
          ...group,
          locked: true,
          collapsed: true,
        })),
      };
      const effective = automaticSystemLayout(projected.topology, saved);
      expect(effective.layoutMode).toBe("automatic");
      expect(effective.positions).toEqual({});
      expect(effective.locks).toEqual({});
      expect(
        effective.groups.every((group) => !group.locked && !group.collapsed),
      ).toBe(true);
      const resolved = resolveTopology(projected.topology, effective);
      expect(resolved.nodes).toHaveLength(projected.topology.nodes.length);
      for (const node of resolved.nodes) {
        expect(node.position).toEqual(position(projected, node.id));
        expect(node.locked).toBe(false);
      }
    },
  );

  it("preserves camera, perspectives, personal groups, catalog labels and colors without mutating saved state", () => {
    const projected = fixture();
    const saved = {
      ...projected.workspace,
      positions: { parent: { x: 83, z: -42 } },
      locks: { parent: true },
      camera: {
        position: [20, 30, 40] as [number, number, number],
        target: [1, 2, 3] as [number, number, number],
        zoom: 2,
      },
      perspectives: [
        { id: "view", name: "Overview", camera: projected.workspace.camera },
      ],
      personalGroups: [
        {
          id: "personal:watch",
          name: "Watch",
          color: "#aabbcc",
          memberIds: ["parent"],
        },
      ],
    };
    const before = structuredClone(saved);
    const effective = automaticSystemLayout(projected.topology, saved);
    expect(effective.camera).toBe(saved.camera);
    expect(effective.personalGroups).toBe(saved.personalGroups);
    expect(effective.perspectives).toBe(saved.perspectives);
    expect(
      effective.groups.map(({ id, name, color }) => ({ id, name, color })),
    ).toEqual(saved.groups.map(({ id, name, color }) => ({ id, name, color })));
    expect(saved).toEqual(before);
  });

  it("places newly added entities automatically and recalculates existing objects from the current catalog", () => {
    const before = fixture();
    const saved = {
      ...before.workspace,
      layoutMode: "manual" as const,
      positions: Object.fromEntries(
        before.topology.nodes.map((node) => [node.id, node.position]),
      ),
      locks: { sibling: true },
    };
    saved.positions.sibling = { x: 80, z: -30 };
    before.system.devices.unshift({
      id: "new",
      label: "New",
      kind: "machine",
      connection_id: "broker",
    });
    const after = projectSystemDocument(before.system);
    const effective = automaticSystemLayout(after.topology, saved);
    const resolved = resolveTopology(after.topology, effective);
    for (const node of resolved.nodes)
      expect(node.position).toEqual(
        after.topology.nodes.find((entry) => entry.id === node.id)!.position,
      );
    expect(resolved.nodes.find((node) => node.id === "new")).toBeDefined();
    expect(resolved.nodes.find((node) => node.id === "sibling")?.locked).toBe(
      false,
    );
  });

  it("keeps personal organization additional to true catalog ownership and independent of placement", () => {
    const projected = fixture();
    const saved = {
      ...projected.workspace,
      memberships: {
        ...projected.workspace.memberships,
        parent: "system:ungrouped",
      },
      personalGroups: [
        {
          id: "personal:watch",
          name: "Watch",
          color: "#aabbcc",
          memberIds: ["parent", "standalone"],
        },
      ],
    };
    const effective = automaticSystemLayout(projected.topology, saved);
    expect(effective.memberships.parent).toBe("assembly");
    expect(effective.personalGroups).toBe(saved.personalGroups);
    const plain = resolveTopology(
      projected.topology,
      automaticSystemLayout(projected.topology, projected.workspace),
    );
    const grouped = resolveTopology(projected.topology, effective);
    expect(
      grouped.nodes.map((node) => ({
        id: node.id,
        position: node.position,
        system: node.system,
      })),
    ).toEqual(
      plain.nodes.map((node) => ({
        id: node.id,
        position: node.position,
        system: node.system,
      })),
    );
    expect(grouped.edges).toEqual(plain.edges);
  });
});
