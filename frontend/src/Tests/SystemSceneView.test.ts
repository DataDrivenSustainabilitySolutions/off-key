import { describe, expect, it } from "vitest";
import { resolveTopology } from "@/features/spatial/model";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import { focusSystemTopology } from "@/features/spatial/focusedSystemTopology";
import {
  colorSystemTopology,
  scopeSystemTopology,
} from "@/features/spatial/systemSceneView";
import type { SystemDocument } from "@/features/spatial/systemTypes";
import type { SpatialWorkspace, Topology } from "@/features/spatial/types";

function fixture() {
  const system: SystemDocument = {
    ...createEmptySystem("Generic system"),
    connections: ["edge", "cloud", "other"].map((id) => ({
      id,
      label: `${id} broker`,
      protocol: "mqtt",
      host: `${id}.example.test`,
      port: 1883,
      transport: "tcp",
      tls: false,
    })),
    devices: [
      { id: "line", label: "Line", kind: "line", connection_id: "edge" },
      { id: "station", label: "Station", kind: "station", parent_id: "line" },
      { id: "probe", label: "Probe", kind: "probe", parent_id: "station" },
      {
        id: "sibling",
        label: "Sibling",
        kind: "machine",
        connection_id: "edge",
      },
      {
        id: "cloud-sibling",
        label: "Cloud sibling",
        kind: "machine",
        connection_id: "cloud",
      },
    ],
    streams: [
      { id: "line-state", device_id: "line", connection_id: "edge" },
      { id: "line-temperature", device_id: "line", connection_id: "cloud" },
      {
        id: "station-temperature",
        device_id: "station",
        connection_id: "edge",
      },
      { id: "probe-value", device_id: "probe", connection_id: "cloud" },
      { id: "sibling-state", device_id: "sibling", connection_id: "edge" },
      {
        id: "cloud-sibling-state",
        device_id: "cloud-sibling",
        connection_id: "cloud",
      },
      { id: "standalone", connection_id: "edge" },
    ].map((stream) => ({
      ...stream,
      label: stream.id,
      topic: `lab/${stream.id}`,
      value_type: "number",
      category: "Measurements",
    })),
    groups: [
      {
        id: "physical-line",
        label: "Physical line",
        color: "#224466",
        member_ids: ["line", "station"],
      },
    ],
  };
  const projected = projectSystemDocument(system);
  const topology: Topology = {
    ...projected.topology,
    nodes: projected.topology.nodes.map((node, index) => ({
      ...node,
      position: { x: index * 3, z: index * -2 },
    })),
  };
  return { topology, workspace: projected.workspace, system };
}
const ids = (topology: Topology) =>
  new Set(topology.nodes.map((node) => node.id));
function grouped(workspace: SpatialWorkspace): SpatialWorkspace {
  return {
    ...workspace,
    personalGroups: [
      {
        id: "personal:readings",
        name: "Individual readings",
        color: "#cc3344",
        memberIds: ["line-state", "station"],
      },
      {
        id: "personal:line",
        name: "Whole line",
        color: "#33aa77",
        memberIds: ["line"],
      },
    ],
  };
}

describe("personal scope over the real system structure", () => {
  it("includes entity descendants and all actual source brokers without pulling their unrelated siblings", () => {
    const { topology } = fixture();
    const before = structuredClone(topology);
    const scoped = scopeSystemTopology(topology, new Set(["line"]));
    expect(ids(scoped)).toEqual(
      new Set([
        "edge",
        "cloud",
        "line",
        "station",
        "probe",
        "line-state",
        "line-temperature",
        "station-temperature",
        "probe-value",
      ]),
    );
    expect(scoped.edges).toContainEqual({
      id: "parent:probe",
      source: "probe",
      target: "station",
    });
    expect(
      scoped.edges.some(
        (edge) => edge.source === "line" && edge.target === "cloud",
      ),
    ).toBe(true);
    expect(topology).toEqual(before);
  });

  it("can start from a measurement and includes its entity and source, without unrelated entities", () => {
    const { topology } = fixture();
    expect(
      ids(scopeSystemTopology(topology, new Set(["probe-value"]))),
    ).toEqual(new Set(["cloud", "probe", "probe-value"]));
    expect(ids(scopeSystemTopology(topology, new Set(["standalone"])))).toEqual(
      new Set(["edge", "standalone"]),
    );
  });

  it("treats an explicitly grouped broker as its whole structural region, while additional source brokers remain context", () => {
    const { topology } = fixture();
    const scoped = scopeSystemTopology(topology, new Set(["edge"]));
    expect(ids(scoped)).toContain("line");
    expect(ids(scoped)).toContain("station");
    expect(ids(scoped)).toContain("probe");
    expect(ids(scoped)).toContain("sibling");
    expect(ids(scoped)).toContain("standalone");
    expect(ids(scoped)).toContain("cloud");
    expect(ids(scoped)).not.toContain("cloud-sibling");
    expect(ids(scoped)).not.toContain("other");
  });

  it("retains hierarchy after scene resolution replaces original edge identifiers", () => {
    const { topology, workspace } = fixture();
    const resolved = resolveTopology(topology, workspace);
    expect(resolved.edges.some((edge) => edge.id.startsWith("parent:"))).toBe(
      false,
    );
    const scoped = scopeSystemTopology(resolved, new Set(["line"]));
    for (const id of ["station", "probe", "station-temperature", "probe-value"])
      expect(ids(scoped)).toContain(id);
  });

  it("leaves the full topology alone without a scope and handles an empty or obsolete selection", () => {
    const { topology } = fixture();
    expect(scopeSystemTopology(topology)).toBe(topology);
    expect(scopeSystemTopology(topology, new Set())).toEqual({
      nodes: [],
      edges: [],
    });
    expect(scopeSystemTopology(topology, new Set(["removed"]))).toEqual({
      nodes: [],
      edges: [],
    });
  });
});

describe("personal colors remain a presentation overlay", () => {
  it("lets the selected group's color win for entities, descendants, and owned readings without mutating catalog ownership", () => {
    const { topology, workspace, system } = fixture();
    const saved = grouped(workspace);
    const beforeTopology = structuredClone(topology);
    const beforeWorkspace = structuredClone(saved);
    const beforeSystem = structuredClone(system);
    const colored = colorSystemTopology(topology, saved, "personal:line");
    for (const id of [
      "line",
      "station",
      "probe",
      "line-state",
      "line-temperature",
      "station-temperature",
      "probe-value",
    ])
      expect(colored.nodes.find((node) => node.id === id)?.color).toBe(
        "#33aa77",
      );
    expect(
      colored.nodes.find((node) => node.id === "sibling")?.color,
    ).toBeUndefined();
    expect(
      colored.nodes.find((node) => node.id === "edge")?.color,
    ).toBeUndefined();
    expect(topology).toEqual(beforeTopology);
    expect(saved).toEqual(beforeWorkspace);
    expect(system).toEqual(beforeSystem);
    expect(colored.edges).toBe(topology.edges);
    for (const node of colored.nodes) {
      const original = topology.nodes.find((entry) => entry.id === node.id)!;
      expect(node.system).toBe(original.system);
      expect(node.groupId).toBe(original.groupId);
      expect(node.position).toBe(original.position);
    }
  });

  it("makes a grouped hidden stream discoverable through its owner's color, without coloring broker siblings", () => {
    const { topology, workspace } = fixture();
    const saved = {
      ...workspace,
      personalGroups: [
        {
          id: "personal:probe",
          name: "Probe reading",
          color: "#aabbcc",
          memberIds: ["probe-value"],
        },
      ],
    };
    const colored = colorSystemTopology(topology, saved, "personal:probe");
    expect(colored.nodes.find((node) => node.id === "probe")?.color).toBe(
      "#aabbcc",
    );
    expect(colored.nodes.find((node) => node.id === "probe-value")?.color).toBe(
      "#aabbcc",
    );
    for (const id of ["cloud", "cloud-sibling", "cloud-sibling-state", "line"])
      expect(
        colored.nodes.find((node) => node.id === id)?.color,
      ).toBeUndefined();
  });

  it("tints a standalone reading's broker summary without coloring unrelated entities or readings", () => {
    const { topology, workspace } = fixture();
    const saved = {
      ...workspace,
      personalGroups: [
        {
          id: "personal:clock",
          name: "Clock",
          color: "#aabbcc",
          memberIds: ["standalone"],
        },
      ],
    };
    const colored = colorSystemTopology(topology, saved, "personal:clock");
    const overview = focusSystemTopology(colored, null).topology;
    expect(overview.nodes.find((node) => node.id === "edge")?.color).toBe(
      "#aabbcc",
    );
    for (const id of [
      "line",
      "station",
      "sibling",
      "sibling-state",
      "line-state",
    ])
      expect(
        colored.nodes.find((node) => node.id === id)?.color,
      ).toBeUndefined();
  });

  it("uses the other selected group for its explicit readings and subtrees while preserving unrelated colors", () => {
    const { topology, workspace } = fixture();
    const colored = colorSystemTopology(
      topology,
      grouped(workspace),
      "personal:readings",
    );
    expect(colored.nodes.find((node) => node.id === "line")?.color).toBe(
      "#cc3344",
    );
    for (const id of [
      "station",
      "probe",
      "line-state",
      "station-temperature",
      "probe-value",
    ])
      expect(colored.nodes.find((node) => node.id === id)?.color).toBe(
        "#cc3344",
      );
    expect(colorSystemTopology(topology, workspace, null)).toBe(topology);
  });
});
