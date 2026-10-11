import { describe, expect, it } from "vitest";
import { parseSpatialCatalog } from "@/features/spatial/catalog";
import { reconcileCatalogWorkspace } from "@/features/spatial/catalogWorkspace";
import {
  createDefaultWorkspace,
  moveNodes,
  resolveTopology,
} from "@/features/spatial/model";
import { parseWorkspace } from "@/features/spatial/workspace";
import type { SpatialGroup } from "@/features/spatial/types";

const id = (index: number) =>
  `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`;
function catalog(count = 2) {
  return parseSpatialCatalog(JSON.stringify({
    schema_version: 1,
    provider: "ambibox",
    default_policy: { mode: "off", interval_seconds: 10 },
    sources: Array.from({ length: count }, (_, index) => ({
      id: id(index),
      label: `Example broker ${index}`,
      host: `broker-${index}.example.invalid`,
      chargers: [{
        id: id(1000 + index),
        local_id: "0",
        label: `Example charger ${index}`,
        policy: null,
        sensors: [{
          key: "reading",
          label: "Example reading",
          value_type: "number",
          upstream_topic: "device/evCharger/0/reading",
        }],
      }],
    })),
  }));
}
const custom = (index = 0): SpatialGroup => ({
  id: `custom-example-${index}`,
  name: `My collection ${index}`,
  color: "#1277bb",
  collapsed: false,
  locked: false,
});

describe("catalog presentation reconciliation", () => {
  it("restores required fleet containment when a demo or foreign layout is imported", () => {
    const imported = catalog();
    const workspace = createDefaultWorkspace();
    workspace.camera = { position: [10, 12, 16], target: [4, 0, 6], zoom: 2 };
    workspace.positions = { "sensor-1": { x: 14, z: 5 } };
    workspace.locks = { "sensor-1": true };
    workspace.memberships = { "sensor-1": "workshop" };
    workspace.perspectives = [{ id: "plan", name: "Plan", camera: workspace.camera, view: "top" }];
    const before = JSON.stringify(workspace);
    const reconciled = reconcileCatalogWorkspace(imported, workspace);
    expect(reconciled.groups).toEqual(imported.groups);
    expect(reconciled.memberships).toEqual(Object.fromEntries(imported.topology.nodes.map((node) => [node.id, node.groupId])));
    expect(reconciled.camera).toEqual(workspace.camera);
    expect(reconciled.positions).toEqual(workspace.positions);
    expect(reconciled.locks).toEqual(workspace.locks);
    expect(reconciled.perspectives).toEqual(workspace.perspectives);
    expect(resolveTopology(imported.topology, reconciled).nodes).toHaveLength(2);
    expect(parseWorkspace(JSON.stringify(reconciled))).toEqual(reconciled);
    expect(JSON.stringify(workspace)).toBe(before);
  });

  it("preserves saved fleet changes and manual custom grouping without changing routes", () => {
    const imported = catalog();
    const stream = imported.topology.nodes.find((node) => node.kind === "sensor")!;
    const edited = { ...imported.groups[0]!, name: "Assembly", color: "#bb7712", collapsed: false, locked: true };
    const workspace = {
      ...createDefaultWorkspace(),
      groups: [custom(), edited],
      memberships: { [stream.id]: custom().id },
      positions: { [stream.id]: { x: 15, z: 9 } },
      locks: { [stream.id]: true },
    };
    const reconciled = reconcileCatalogWorkspace(imported, workspace);
    expect(reconciled.groups).toEqual([edited, imported.groups[1], custom()]);
    expect(reconciled.memberships[stream.id]).toBe(custom().id);
    const projected = resolveTopology(imported.topology, reconciled);
    expect(projected.nodes.find((node) => node.id === stream.id)).toMatchObject({ groupId: custom().id, position: { x: 15, z: 9 }, locked: true, brokerId: stream.brokerId, catalog: stream.catalog });
    expect(projected.edges.find((edge) => edge.source === stream.id)?.target).toBe(stream.brokerId);
    expect(reconcileCatalogWorkspace(imported, reconciled)).toEqual(reconciled);
  });

  it("falls back to deterministic catalog memberships when saved group references are absent", () => {
    const imported = catalog();
    const [first, second] = imported.topology.nodes.filter((node) => node.kind === "sensor");
    const workspace = {
      ...createDefaultWorkspace(),
      groups: [imported.groups[1]!, { ...custom(), id: "foreign-collection" }],
      memberships: {
        [first!.id]: "foreign-collection",
        [second!.id]: imported.groups[0]!.id,
        "missing-node": "deleted-group",
      },
    };
    const reconciled = reconcileCatalogWorkspace(imported, workspace);
    expect(reconciled.groups).toEqual(imported.groups);
    expect(reconciled.memberships[first!.id]).toBe(first!.groupId);
    expect(reconciled.memberships[second!.id]).toBe(imported.groups[0]!.id);
    expect(reconciled.memberships).not.toHaveProperty("missing-node");
  });

  it("prioritizes every required collection over extras within the persistence budget", () => {
    const imported = catalog(127);
    const stream = imported.topology.nodes.find((node) => node.kind === "sensor")!;
    const workspace = {
      ...createDefaultWorkspace(),
      groups: [custom(0), custom(1)],
      memberships: { [stream.id]: custom(1).id },
    };
    const reconciled = reconcileCatalogWorkspace(imported, workspace);
    expect(reconciled.groups).toHaveLength(128);
    expect(reconciled.groups.slice(0, 127)).toEqual(imported.groups);
    expect(reconciled.groups[127]).toEqual(custom(0));
    expect(reconciled.memberships[stream.id]).toBe(stream.groupId);
    expect(parseWorkspace(JSON.stringify(reconciled))).toEqual(reconciled);
  });

  it("accepts unique valid custom collections and ignores invalid or foreign extras", () => {
    const imported = catalog();
    const workspace = {
      ...createDefaultWorkspace(),
      groups: [
        custom(),
        { ...custom(), name: "Duplicate" },
        { ...custom(1), id: "custom-" },
        { ...custom(2), id: "foreign-group" },
        { ...custom(3), color: "red" },
        { ...custom(4), name: " " },
      ],
    };
    expect(reconcileCatalogWorkspace(imported, workspace).groups).toEqual([...imported.groups, custom()]);
  });

  it("seeds membership for brokers, chargers and sensors so collection locks cover every object", () => {
    const imported = catalog();
    const locked = { ...imported.groups[0]!, locked: true };
    const workspace = reconcileCatalogWorkspace(imported, {
      ...createDefaultWorkspace(),
      groups: [locked],
    });
    const members = imported.topology.nodes.filter((node) => node.groupId === locked.id);
    expect(members.map((node) => node.kind)).toEqual(["broker", "charger", "sensor"]);
    expect(Object.keys(workspace.memberships)).toHaveLength(imported.topology.nodes.length);
    for (const member of members) {
      expect(moveNodes(workspace, { [member.id]: { x: 100, z: 100 } }).positions[member.id]).toBeUndefined();
    }
  });
});
