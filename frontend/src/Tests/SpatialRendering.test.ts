import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { SpatialConnectionLayer } from "../features/spatial/SpatialConnectionLayer";
import { SpatialNodeLayer } from "../features/spatial/SpatialNodeLayer";
import {
  curvePoint,
  fitCameraDepth,
  groupBounds,
  nodeVisualKind,
  nodeVisualHeight,
  sceneNodeLabel,
  visibleSceneLabels,
} from "../features/spatial/sceneGeometry";
import type { SpatialNode } from "../features/spatial/types";

const sensor: SpatialNode = {
  id: "sensor-1",
  label: "Temperature",
  kind: "sensor",
  groupId: "room",
  position: { x: -5, z: 0 },
  locked: false,
  unit: "°C",
  metric: "Temperature",
  baseRate: 1,
};

function topCamera() {
  const camera = new THREE.OrthographicCamera(-20, 20, 15, -15, 0.1, 100);
  camera.position.set(0, 20, 0.01);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  return camera;
}

describe("spatial rendering geometry", () => {
  it("fits a large map in front of the camera instead of clipping it behind the near plane", () => {
    const bounds = { minX: -92, maxX: 92, minZ: -5, maxZ: 65 };
    const target = new THREE.Vector3(0, 0, 30);
    const direction = new THREE.Vector3(22, 28, 30).normalize();
    const camera = new THREE.OrthographicCamera(-200, 200, 150, -150, 0.1, 400);
    const corners: THREE.Vector3[] = [];
    for (const x of [bounds.minX, bounds.maxX])
      for (const z of [bounds.minZ, bounds.maxZ])
        for (const y of [0, 1.25]) corners.push(new THREE.Vector3(x, y, z));
    const depthVisible = (point: THREE.Vector3) => {
      const projected = point.clone().project(camera);
      return projected.z >= -1 && projected.z <= 1;
    };
    camera.position.copy(target).addScaledVector(direction, 46);
    camera.lookAt(target);
    camera.updateMatrixWorld();
    expect(corners.every(depthVisible)).toBe(false);
    const depth = fitCameraDepth(bounds, 46);
    camera.position.copy(target).addScaledVector(direction, depth.distance);
    camera.far = depth.far;
    camera.updateProjectionMatrix();
    camera.lookAt(target);
    camera.updateMatrixWorld();
    expect(corners.every(depthVisible)).toBe(true);
  });
  it("keeps instanced objects selectable at their new position after a drag", () => {
    const layer = new SpatialNodeLayer();
    const positions = new Map([[sensor.id, { ...sensor.position }]]);
    const groups = [
      {
        id: "room",
        name: "Room",
        color: "#52829b",
        collapsed: false,
        locked: false,
      },
    ];
    const camera = topCamera();
    const pick = (x: number) => {
      layer.object.updateMatrixWorld(true);
      const ray = new THREE.Raycaster(
        new THREE.Vector3(x, 20, 0),
        new THREE.Vector3(0, -1, 0),
      );
      const hit = ray.intersectObjects(layer.pickables, false)[0];
      return hit ? layer.nodeForIntersection(hit) : null;
    };
    try {
      layer.update([sensor], positions, groups, null, camera);
      expect(pick(-5)).toBe(sensor.id);
      positions.set(sensor.id, { x: 5, z: 0 });
      layer.update([sensor], positions, groups, null, camera);
      expect(pick(5)).toBe(sensor.id);
      expect(pick(-5)).toBeNull();
    } finally {
      layer.dispose();
    }
  });

  it("renders collapsed and expanded charger anchors together without losing their selection IDs", () => {
    const layer = new SpatialNodeLayer();
    const charger: SpatialNode = {
      ...sensor,
      id: "charger-1",
      kind: "charger",
      catalog: { sourceId: "catalog", chargerId: "charger-1" },
    };
    const collapsed: SpatialNode = {
      ...charger,
      id: "group:charger-2",
      kind: "group",
      groupId: "charger-2",
      position: { x: 5, z: 0 },
      catalog: { sourceId: "catalog", chargerId: "charger-2" },
    };
    const positions = new Map(
      [charger, collapsed].map((node) => [node.id, node.position]),
    );
    const camera = topCamera();
    try {
      layer.update([charger, collapsed], positions, [], collapsed.id, camera);
      layer.object.updateMatrixWorld(true);
      const pick = (x: number) => {
        const ray = new THREE.Raycaster(
          new THREE.Vector3(x, 20, 0),
          new THREE.Vector3(0, -1, 0),
        );
        const hit = ray.intersectObjects(layer.pickables, false)[0];
        return hit ? layer.nodeForIntersection(hit) : null;
      };
      expect(nodeVisualKind(collapsed)).toBe("charger");
      expect(layer.visibleCount).toBe(2);
      expect(pick(-5)).toBe(charger.id);
      expect(pick(5)).toBe(collapsed.id);
      expect(pick(6)).toBe(collapsed.id);
      expect(pick(-4)).toBeNull();
      expect(nodeVisualHeight(collapsed)).toBeGreaterThan(
        nodeVisualHeight(charger) * 2,
      );
      // The same GPU batch holds both assets rather than adding meshes for every charger.
      expect(layer.pickables.filter((mesh) => mesh.count === 2)).toHaveLength(
        1,
      );
      const bounds = groupBounds([collapsed], positions).get("charger-2")!;
      expect(bounds.minX).toBeCloseTo(2.35);
      expect(bounds.maxX).toBeCloseTo(7.65);
      expect(bounds.minZ).toBeCloseTo(-2.65);
      expect(bounds.maxZ).toBeCloseTo(2.65);
    } finally {
      layer.dispose();
    }
  });

  it("keeps fleet labels compact while retaining exact names on focused objects", () => {
    const node: SpatialNode = {
      ...sensor,
      kind: "group",
      label: "AmbiBox charger 1000279",
      catalog: { sourceId: "catalog", chargerId: "charger-1", localId: "0" },
    };
    expect(sceneNodeLabel(node)).toBe("AmbiBox charge…");
    expect(sceneNodeLabel(node, true)).toBe(node.label);
    expect(sceneNodeLabel(sensor)).toBe(sensor.label);
  });

  it("suppresses overlapping labels but keeps selected and hovered identities visible", () => {
    const labels = [
      { id: "background", x: 10, y: 10, width: 80, height: 27, priority: 0 },
      { id: "selected", x: 10, y: 10, width: 190, height: 27, priority: 2 },
      { id: "hovered", x: 20, y: 10, width: 190, height: 27, priority: 1 },
      { id: "clear", x: 230, y: 10, width: 80, height: 27, priority: 0 },
    ];
    expect([...visibleSceneLabels(labels)]).toEqual([
      "selected",
      "hovered",
      "clear",
    ]);
    expect(labels[0]?.id).toBe("background");
    expect(
      visibleSceneLabels(
        Array.from({ length: 100 }, (_, index) => ({
          id: String(index),
          x: index * 100,
          y: 0,
          width: 80,
          height: 27,
          priority: 0,
        })),
      ).size,
    ).toBe(40);
  });

  it("does not invent traffic pulses for a catalog charger with no subscription edge", () => {
    const layer = new SpatialConnectionLayer();
    const charger: SpatialNode = {
      ...sensor,
      id: "charger",
      kind: "charger",
    };
    try {
      layer.setTopology([charger], [], [], "balanced");
      layer.updateLines(new Map([[charger.id, charger.position]]), charger.id);
      expect(
        layer.receive({ nodeId: charger.id, timestamp: 1, value: 0 }, 1500),
      ).toBe(false);
      expect(layer.activeCount).toBe(0);
    } finally {
      layer.dispose();
    }
  });

  it("keeps pulse visualization bounded and reserves capacity for the inspected sensor", () => {
    const layer = new SpatialConnectionLayer();
    const broker: SpatialNode = {
      ...sensor,
      id: "broker",
      kind: "broker",
      position: { x: 0, z: 0 },
    };
    const inspected: SpatialNode = {
      ...sensor,
      id: "inspected",
      position: { x: 5, z: 0 },
    };
    const nodes = [sensor, inspected, broker];
    const edges = [
      { id: "a", source: sensor.id, target: broker.id },
      { id: "b", source: inspected.id, target: broker.id },
    ];
    try {
      layer.setTopology(nodes, edges, [], "balanced");
      layer.updateLines(
        new Map(nodes.map((node) => [node.id, node.position])),
        inspected.id,
      );
      let background = 0;
      for (let index = 0; index < 1000; index += 1)
        if (layer.receive({ nodeId: sensor.id, timestamp: 1, value: 20 }, 1500))
          background += 1;
      expect(background).toBeLessThan(80);
      expect(
        layer.receive({ nodeId: inspected.id, timestamp: 1, value: 20 }, 1500),
      ).toBe(true);
      let selected = 1;
      for (let index = 0; index < 1000; index += 1)
        if (
          layer.receive({ nodeId: inspected.id, timestamp: 1, value: 20 }, 1500)
        )
          selected += 1;
      expect(background + selected).toBe(80);
      expect(
        layer.receive({ nodeId: sensor.id, timestamp: 1, value: 20 }, 2501),
      ).toBe(true);
    } finally {
      layer.dispose();
    }
  });

  it("keeps event pulse endpoints attached when connections move", () => {
    const source = { x: -4, z: 2 };
    const target = { x: 8, z: -3 };
    const point = { x: 0, y: 0, z: 0 };
    curvePoint(source, target, -0.2, point);
    expect({ x: point.x, z: point.z }).toEqual(source);
    curvePoint(source, target, 1.2, point);
    expect({ x: point.x, z: point.z }).toEqual(target);
    target.x = 12;
    target.z = 5;
    curvePoint(source, target, 1, point);
    expect({ x: point.x, z: point.z }).toEqual(target);
  });
});
