import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import {
  projectSystemDocument,
  reconcileSystemWorkspace,
} from "@/features/spatial/systemProjection";
import { focusSystemTopology } from "@/features/spatial/focusedSystemTopology";
import { SpatialConnectionLayer } from "@/features/spatial/SpatialConnectionLayer";
import { SpatialNodeLayer } from "@/features/spatial/SpatialNodeLayer";
import {
  nodeVisualHeight,
  nodeVisualKind,
} from "@/features/spatial/sceneGeometry";
import type { SystemDocument } from "@/features/spatial/systemTypes";

function fixture(): SystemDocument {
  return {
    ...createEmptySystem("Generic system"),
    connections: ["shared", "dedicated"].map((id) => ({
      id,
      label: `${id} broker`,
      protocol: "mqtt",
      host: `${id}.example.test`,
      port: 1883,
      transport: "tcp",
      tls: false,
    })),
    devices: [
      { id: "room", label: "Office", kind: "room", connection_id: "shared" },
      {
        id: "machine",
        label: "Machine",
        kind: "machine",
        connection_id: "shared",
      },
      {
        id: "cabinet",
        label: "Cabinet",
        kind: "cabinet",
        connection_id: "dedicated",
      },
    ],
    streams: [
      {
        id: "temperature",
        label: "Temperature",
        connection_id: "shared",
        device_id: "room",
        topic: "office/environment",
        payload_pointer: "/temperature",
        value_type: "number",
        category: "Environment",
      },
      {
        id: "humidity",
        label: "Humidity",
        connection_id: "shared",
        device_id: "room",
        topic: "office/environment",
        payload_pointer: "/humidity",
        value_type: "number",
        category: "Environment",
      },
      {
        id: "cabinet-power",
        label: "Power",
        connection_id: "dedicated",
        device_id: "cabinet",
        topic: "cabinet/power",
        value_type: "number",
        category: "Power",
      },
      {
        id: "machine-status",
        label: "State",
        connection_id: "shared",
        device_id: "machine",
        topic: "machine/state",
        value_type: "text",
        category: "Status",
      },
      {
        id: "machine-aux",
        label: "Auxiliary",
        connection_id: "dedicated",
        device_id: "machine",
        topic: "aux/machine",
        value_type: "boolean",
        category: "Status",
      },
      {
        id: "standalone",
        label: "Clock",
        connection_id: "shared",
        topic: "clock",
        value_type: "identifier",
        category: "Status",
      },
    ],
    groups: [
      {
        id: "physical-room",
        label: "Physical room",
        member_ids: ["shared", "room", "temperature", "humidity"],
      },
    ],
  };
}

describe("focused generic spatial topology", () => {
  it("keeps shared, dedicated, and multiple broker sources explicit while hiding owned measurements", () => {
    const projection = projectSystemDocument(fixture());
    const focused = focusSystemTopology(projection.topology, null);
    expect(focused.topology.nodes.map((node) => node.id)).toEqual([
      "shared",
      "dedicated",
      "room",
      "machine",
      "cabinet",
    ]);
    expect(focused.hiddenStreams).toBe(6);
    expect(
      focused.topology.edges
        .filter((edge) => edge.source === "machine")
        .map((edge) => edge.target),
    ).toEqual(["shared", "dedicated"]);
    expect(
      focused.topology.edges.filter(
        (edge) => edge.source === "room" && edge.target === "shared",
      ),
    ).toHaveLength(1);
    expect(
      focused.topology.edges.some(
        (edge) => edge.source === "room" && edge.target === "machine",
      ),
    ).toBe(false);
    expect(focused.pulseSources.temperature).toBe("room");
    expect(focused.pulseRoutes["machine-status"]).toEqual({
      source: "machine",
      target: "shared",
    });
    expect(focused.pulseRoutes["machine-aux"]).toEqual({
      source: "machine",
      target: "dedicated",
    });
    expect(focused.pulseRoutes.standalone).toEqual({
      source: "shared",
      target: "shared",
    });
    expect(projection.groups.every((group) => !group.collapsed)).toBe(true);
    expect(
      projection.topology.nodes.find((node) => node.id === "room")?.groupId,
    ).toBe("physical-room");
    expect(focused.groups).toHaveLength(2);
  });

  it("reveals only the selected reading and keeps its actual catalog ownership", () => {
    const projection = projectSystemDocument(fixture());
    const focused = focusSystemTopology(projection.topology, "temperature");
    expect(focused.focusedDeviceId).toBe("room");
    expect(
      focused.topology.nodes
        .filter((node) => node.kind === "sensor")
        .map((node) => node.id),
    ).toEqual(["temperature"]);
    expect(focused.topology.edges).toContainEqual({
      id: "stream:temperature",
      source: "temperature",
      target: "room",
    });
    expect(focused.pulseSources.temperature).toBe("temperature");
    expect(focused.pulseSources["machine-aux"]).toBe("machine");
  });

  it("keeps dense entity selection compact and reveals one specific reading even beyond the first page", () => {
    const system = fixture();
    system.streams = Array.from({ length: 200 }, (_, index) => ({
      ...system.streams[0]!,
      id: `measurement:${index}`,
      topic: `office/value/${index}`,
    }));
    system.groups = [];
    const topology = projectSystemDocument(system).topology;
    const ownerPosition = topology.nodes.find(
      (node) => node.id === "room",
    )!.position;
    const latePosition = topology.nodes.find(
      (node) => node.id === "measurement:199",
    )!.position;
    expect(
      Math.hypot(
        latePosition.x - ownerPosition.x,
        latePosition.z - ownerPosition.z,
      ),
    ).toBeLessThanOrEqual(2.6 + 1e-10);
    const entity = focusSystemTopology(topology, "room");
    expect(entity.topology.nodes.some((node) => node.kind === "sensor")).toBe(
      false,
    );
    expect(entity.hiddenStreams).toBe(200);
    const selected = focusSystemTopology(topology, "measurement:199");
    expect(
      selected.topology.nodes
        .filter((node) => node.kind === "sensor")
        .map((node) => node.id),
    ).toEqual(["measurement:199"]);
    expect(selected.pulseSources["measurement:198"]).toBe("room");
    expect(selected.pulseSources["measurement:199"]).toBe("measurement:199");
    const expanded = focusSystemTopology(topology, "room", {
      showStreams: true,
    });
    expect(
      expanded.topology.nodes.filter((node) => node.kind === "sensor"),
    ).toHaveLength(48);
    const explicit = focusSystemTopology(topology, "measurement:199", {
      showStreams: true,
      streamLimit: 12,
    });
    expect(
      explicit.topology.nodes.filter((node) => node.kind === "sensor"),
    ).toHaveLength(12);
    expect(
      explicit.topology.nodes.some((node) => node.id === "measurement:199"),
    ).toBe(true);
    expect(
      focusSystemTopology(topology, "room", {
        showStreams: true,
        streamLimit: Number.NaN,
      }).topology.nodes.filter((node) => node.kind === "sensor"),
    ).toHaveLength(48);
  });

  it("keeps unowned streams out of the overview and bounds broker expansion while retaining the selected stream", () => {
    const system = fixture();
    system.groups = [];
    system.streams = Array.from({ length: 200 }, (_, index) => ({
      ...system.streams[5]!,
      id: `unowned:${index}`,
      topic: `lab/unowned/${index}`,
    }));
    const topology = projectSystemDocument(system).topology;
    const baseline = projectSystemDocument(fixture()).topology;
    for (const broker of topology.nodes.filter(
      (node) => node.kind === "broker",
    ))
      expect(broker.position).toEqual(
        baseline.nodes.find((node) => node.id === broker.id)!.position,
      );
    const brokerPosition = topology.nodes.find(
      (node) => node.id === "shared",
    )!.position;
    const latePosition = topology.nodes.find(
      (node) => node.id === "unowned:199",
    )!.position;
    expect(
      Math.hypot(
        latePosition.x - brokerPosition.x,
        latePosition.z - brokerPosition.z,
      ),
    ).toBeLessThanOrEqual(4.5 + 1e-10);
    const overview = focusSystemTopology(topology, null);
    expect(overview.topology.nodes.some((node) => node.kind === "sensor")).toBe(
      false,
    );
    expect(overview.pulseSources["unowned:199"]).toBe("shared");
    const broker = focusSystemTopology(topology, "shared");
    expect(broker.topology.nodes.some((node) => node.kind === "sensor")).toBe(
      false,
    );
    const explicit = focusSystemTopology(topology, "shared", {
      showStreams: true,
    });
    expect(
      explicit.topology.nodes.filter((node) => node.kind === "sensor"),
    ).toHaveLength(48);
    const selected = focusSystemTopology(topology, "unowned:199");
    expect(
      selected.topology.nodes
        .filter((node) => node.kind === "sensor")
        .map((node) => node.id),
    ).toEqual(["unowned:199"]);
  });

  it("keeps manual placement, locks, and valid personal memberships after a catalog revision", () => {
    const projection = projectSystemDocument(fixture());
    const saved = {
      ...projection.workspace,
      positions: { machine: { x: 42, z: -10 } },
      locks: { machine: true },
      personalGroups: [
        {
          id: "personal:watch",
          name: "Watch",
          color: "#123456",
          memberIds: ["machine", "removed"],
        },
      ],
    };
    const reconciled = reconcileSystemWorkspace(projection, saved);
    expect(reconciled.positions.machine).toEqual({ x: 42, z: -10 });
    expect(reconciled.locks.machine).toBe(true);
    expect(reconciled.personalGroups?.[0]?.memberIds).toEqual(["machine"]);
    expect(reconciled.memberships.machine).toBe(
      projection.workspace.memberships.machine,
    );
  });

  it("renders generic entities as low neutral selectable objects while keeping catalog charger previews", () => {
    const projection = projectSystemDocument(fixture());
    const entity = projection.topology.nodes.find(
      (node) => node.id === "room",
    )!;
    expect(nodeVisualKind(entity)).toBe("device");
    expect(nodeVisualHeight(entity)).toBeLessThan(0.8);
    const layer = new SpatialNodeLayer();
    const camera = new THREE.OrthographicCamera(-20, 20, 15, -15, 0.1, 100);
    camera.position.set(0, 20, 0.01);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld();
    try {
      const node = { ...entity, position: { x: 0, z: 0 }, color: "#d37a4b" };
      layer.update(
        [node],
        new Map([[node.id, node.position]]),
        [],
        node.id,
        camera,
      );
      layer.object.updateMatrixWorld(true);
      const ray = new THREE.Raycaster(
        new THREE.Vector3(0, 20, 0),
        new THREE.Vector3(0, -1, 0),
      );
      const hit = ray.intersectObjects(layer.pickables, false)[0];
      expect(hit ? layer.nodeForIntersection(hit) : null).toBe(node.id);
      expect(layer.pickables.filter((mesh) => mesh.count === 1)).toHaveLength(
        1,
      );
    } finally {
      layer.dispose();
    }
  });

  it("shows arrivals at their actual visible entity without traveling through other devices, including after movement", () => {
    const focused = focusSystemTopology(
      projectSystemDocument(fixture()).topology,
      null,
    );
    const layer = new SpatialConnectionLayer();
    const positions = new Map(
      focused.topology.nodes.map((node) => [node.id, { ...node.position }]),
    );
    const entity = positions.get("machine")!;
    try {
      layer.setTopology(
        focused.topology.nodes,
        focused.topology.edges,
        focused.groups,
        "balanced",
      );
      layer.updateLines(positions, "machine");
      expect(
        layer.receive(
          { nodeId: "machine", timestamp: 1, value: 2 },
          1500,
          focused.pulseRoutes["machine-status"],
        ),
      ).toBe(true);
      expect(
        layer.receive(
          { nodeId: "machine", timestamp: 1, value: 3 },
          1500,
          focused.pulseRoutes["machine-aux"],
        ),
      ).toBe(true);
      layer.updatePulses(1750, false);
      const points = layer.object.children.find(
        (child): child is THREE.Points => child instanceof THREE.Points,
      )!;
      const attribute = points.geometry.getAttribute("position");
      for (const index of [0, 1]) {
        expect(attribute.getX(index)).toBeCloseTo(entity.x);
        expect(attribute.getZ(index)).toBeCloseTo(entity.z);
      }
      entity.x += 5;
      entity.z -= 3;
      layer.updatePulses(1800, false);
      expect(attribute.getX(0)).toBeCloseTo(entity.x);
      expect(attribute.getZ(0)).toBeCloseTo(entity.z);
      expect(layer.updatePulses(2151, false)).toBe(false);
      expect(layer.activeCount).toBe(0);
    } finally {
      layer.dispose();
    }
  });
});
