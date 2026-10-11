import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import {
  groupBounds,
  nodeVisualKind,
  nodeVisualScale,
  type GroupBounds,
  type NodeVisualKind,
} from "./sceneGeometry";
import type { Point, SpatialGroup, SpatialNode } from "./types";

type NodeBatch = {
  mesh: THREE.InstancedMesh;
  kind: NodeVisualKind | "cap" | "chargerDetail" | "deviceDetail" | "shadow";
  ids: string[];
};

/** Node geometry is instanced; the scene's draw calls do not grow with its node count. */
export class SpatialNodeLayer {
  readonly object = new THREE.Group();
  readonly pickables: THREE.InstancedMesh[] = [];
  bounds = new Map<string, GroupBounds>();
  visibleCount = 0;
  private capacity = 0;
  private batches: NodeBatch[] = [];
  private tiles: THREE.InstancedMesh | null = null;
  private tileEdges: THREE.InstancedMesh | null = null;
  private tileCapacity = 0;
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];
  private readonly transform = new THREE.Object3D();
  private readonly color = new THREE.Color();
  private readonly white = new THREE.Color("#ffffff");
  private readonly matrix = new THREE.Matrix4();
  private readonly frustum = new THREE.Frustum();
  private readonly sphere = new THREE.Sphere(new THREE.Vector3(), 1.2);
  private readonly selection: THREE.Mesh;

  constructor() {
    const geometry = new THREE.TorusGeometry(0.56, 0.028, 5, 48);
    const material = new THREE.MeshBasicMaterial({
      color: "#263e53",
      transparent: true,
      opacity: 0.9,
    });
    this.selection = new THREE.Mesh(geometry, material);
    this.selection.rotation.x = -Math.PI / 2;
    this.selection.visible = false;
    this.object.add(this.selection);
    this.geometries.push(geometry);
    this.materials.push(material);
  }

  private createBatch(
    kind: NodeBatch["kind"],
    geometry: THREE.BufferGeometry,
    material: THREE.Material,
  ) {
    this.geometries.push(geometry);
    this.materials.push(material);
    const mesh = new THREE.InstancedMesh(geometry, material, this.capacity);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    mesh.count = 0;
    this.object.add(mesh);
    this.batches.push({ mesh, kind, ids: [] });
    if (
      kind !== "cap" &&
      kind !== "chargerDetail" &&
      kind !== "deviceDetail" &&
      kind !== "shadow"
    )
      this.pickables.push(mesh);
  }

  private ensureCapacity(count: number) {
    if (count <= this.capacity) return;
    for (const batch of this.batches) {
      this.object.remove(batch.mesh);
      batch.mesh.dispose();
      batch.mesh.geometry.dispose();
      const material = batch.mesh.material;
      if (!Array.isArray(material)) material.dispose();
    }
    this.batches = [];
    this.pickables.length = 0;
    this.capacity = Math.max(32, 2 ** Math.ceil(Math.log2(Math.max(1, count))));
    this.createBatch(
      "broker",
      new RoundedBoxGeometry(1.45, 0.52, 1.1, 2, 0.09),
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        roughness: 0.85,
        metalness: 0.03,
      }),
    );
    this.createBatch(
      "sensor",
      new THREE.CylinderGeometry(0.3, 0.34, 0.4, 16),
      new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.92 }),
    );
    this.createBatch(
      "group",
      new THREE.BoxGeometry(1.25, 0.3, 1.25),
      new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.85 }),
    );
    this.createBatch(
      "device",
      new RoundedBoxGeometry(1.35, 0.34, 0.95, 2, 0.1),
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        roughness: 0.76,
        metalness: 0.025,
      }),
    );
    const deviceDetail = new RoundedBoxGeometry(0.46, 0.025, 0.065, 1, 0.012);
    deviceDetail.translate(0, 0.185, 0.24);
    this.createBatch(
      "deviceDetail",
      deviceDetail,
      new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.8 }),
    );
    this.createBatch(
      "charger",
      new RoundedBoxGeometry(0.88, 1.4, 0.6, 2, 0.09),
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        roughness: 0.72,
        metalness: 0.04,
      }),
    );
    const display = new THREE.BoxGeometry(0.34, 0.26, 0.025);
    display.translate(0, 0.31, 0.308);
    const port = new THREE.TorusGeometry(0.115, 0.024, 5, 16);
    port.translate(0, -0.15, 0.315);
    const detailGeometry = mergeGeometries([display, port])!;
    display.dispose();
    port.dispose();
    this.createBatch(
      "chargerDetail",
      detailGeometry,
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        roughness: 0.6,
        emissive: "#ffffff",
        emissiveIntensity: 0.04,
      }),
    );
    this.createBatch(
      "cap",
      new THREE.CylinderGeometry(0.2, 0.2, 0.04, 16),
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        roughness: 0.7,
        emissive: "#ffffff",
        emissiveIntensity: 0.03,
      }),
    );
    const shadowGeometry = new THREE.CircleGeometry(0.7, 20);
    shadowGeometry.rotateX(-Math.PI / 2);
    this.createBatch(
      "shadow",
      shadowGeometry,
      new THREE.MeshBasicMaterial({
        color: "#25333e",
        transparent: true,
        opacity: 0.055,
        depthWrite: false,
      }),
    );
  }

  private ensureTiles(count: number) {
    if (count <= this.tileCapacity) return;
    for (const tile of [this.tiles, this.tileEdges]) {
      if (!tile) continue;
      this.object.remove(tile);
      tile.dispose();
      tile.geometry.dispose();
      const material = tile.material;
      if (!Array.isArray(material)) material.dispose();
    }
    this.tileCapacity = Math.max(8, count);
    const body = new THREE.BoxGeometry(1, 1, 1);
    const edge = new THREE.BoxGeometry(1, 1, 1);
    const bodyMaterial = new THREE.MeshStandardMaterial({
      color: "#ffffff",
      roughness: 1,
    });
    const edgeMaterial = new THREE.MeshBasicMaterial({ color: "#ffffff" });
    this.geometries.push(body, edge);
    this.materials.push(bodyMaterial, edgeMaterial);
    this.tiles = new THREE.InstancedMesh(body, bodyMaterial, this.tileCapacity);
    this.tileEdges = new THREE.InstancedMesh(
      edge,
      edgeMaterial,
      this.tileCapacity,
    );
    this.tiles.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.tileEdges.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.tiles.frustumCulled = false;
    this.tileEdges.frustumCulled = false;
    this.object.add(this.tileEdges, this.tiles);
  }

  update(
    nodes: SpatialNode[],
    positions: ReadonlyMap<string, Point>,
    groups: SpatialGroup[],
    selectedId: string | null,
    camera: THREE.Camera,
  ) {
    this.ensureCapacity(nodes.length);
    this.ensureTiles(groups.length);
    this.matrix.multiplyMatrices(
      camera.projectionMatrix,
      camera.matrixWorldInverse,
    );
    this.frustum.setFromProjectionMatrix(this.matrix);
    const colors = new Map(groups.map((group) => [group.id, group.color]));
    const counts: Record<NodeBatch["kind"], number> = {
      broker: 0,
      sensor: 0,
      group: 0,
      charger: 0,
      device: 0,
      deviceDetail: 0,
      chargerDetail: 0,
      cap: 0,
      shadow: 0,
    };
    const byKind = new Map(this.batches.map((batch) => [batch.kind, batch]));
    this.visibleCount = 0;
    for (const batch of this.batches) batch.ids.length = 0;
    for (const node of nodes) {
      const position = positions.get(node.id) ?? node.position;
      const kind = nodeVisualKind(node);
      const scale = nodeVisualScale(node);
      this.sphere.radius = 1.2 * scale;
      this.sphere.center.set(
        position.x,
        kind === "charger" ? 0.09 + 0.72 * scale : 0.4,
        position.z,
      );
      if (!this.frustum.intersectsSphere(this.sphere)) continue;
      this.visibleCount += 1;
      const batch = byKind.get(kind);
      if (!batch) continue;
      const index = counts[kind]++;
      batch.ids.push(node.id);
      this.transform.position.set(
        position.x,
        kind === "charger"
          ? 0.09 + 0.72 * scale
          : kind === "broker"
            ? 0.36
            : kind === "group"
              ? 0.23
              : kind === "device"
                ? 0.29
                : 0.3,
        position.z,
      );
      this.transform.scale.set(scale, scale, scale);
      this.transform.updateMatrix();
      batch.mesh.setMatrixAt(index, this.transform.matrix);
      this.color
        .set(node.color ?? colors.get(node.groupId) ?? "#6b8daf")
        .lerp(this.white, kind === "broker" ? 0.87 : 0.92);
      batch.mesh.setColorAt(index, this.color);
      const detail = byKind.get("chargerDetail");
      if (kind === "charger" && detail) {
        const detailIndex = counts.chargerDetail++;
        detail.mesh.setMatrixAt(detailIndex, this.transform.matrix);
        this.color.set(node.color ?? colors.get(node.groupId) ?? "#6b8daf");
        detail.mesh.setColorAt(detailIndex, this.color);
      }
      const entityDetail = byKind.get("deviceDetail");
      if (kind === "device" && entityDetail) {
        const detailIndex = counts.deviceDetail++;
        entityDetail.mesh.setMatrixAt(detailIndex, this.transform.matrix);
        this.color.set(node.color ?? colors.get(node.groupId) ?? "#6b8daf");
        entityDetail.mesh.setColorAt(detailIndex, this.color);
      }
      const cap = byKind.get("cap");
      if (cap && kind !== "charger" && kind !== "device") {
        const capIndex = counts.cap++;
        cap.ids.push(node.id);
        this.transform.position.y =
          kind === "broker" ? 0.647 : kind === "group" ? 0.403 : 0.522;
        this.transform.scale.set(
          kind === "broker" ? 1.65 : kind === "group" ? 1.5 : 1,
          1,
          kind === "broker" ? 1.65 : kind === "group" ? 1.5 : 1,
        );
        this.transform.updateMatrix();
        cap.mesh.setMatrixAt(capIndex, this.transform.matrix);
        this.color.set(node.color ?? colors.get(node.groupId) ?? "#6b8daf");
        cap.mesh.setColorAt(capIndex, this.color);
      }
      const shadow = byKind.get("shadow");
      if (shadow) {
        const shadowIndex = counts.shadow++;
        this.transform.position.set(
          position.x + 0.06,
          0.091,
          position.z + 0.08,
        );
        this.transform.scale.set(
          (kind === "broker"
            ? 1.35
            : kind === "charger"
              ? 0.9
              : kind === "device"
                ? 1.2
                : 0.75) * scale,
          1,
          (kind === "broker"
            ? 1.03
            : kind === "charger"
              ? 0.65
              : kind === "device"
                ? 0.85
                : 0.75) * scale,
        );
        this.transform.updateMatrix();
        shadow.mesh.setMatrixAt(shadowIndex, this.transform.matrix);
      }
    }
    for (const batch of this.batches) {
      batch.mesh.count = counts[batch.kind];
      batch.mesh.instanceMatrix.needsUpdate = true;
      // InstancedMesh caches its bounds; invalidate after movement/camera culling so picking remains correct.
      if (
        batch.kind === "broker" ||
        batch.kind === "sensor" ||
        batch.kind === "group" ||
        batch.kind === "charger" ||
        batch.kind === "device"
      )
        batch.mesh.computeBoundingSphere();
      if (batch.mesh.instanceColor) batch.mesh.instanceColor.needsUpdate = true;
    }
    this.bounds = groupBounds(nodes, positions);
    if (this.tiles && this.tileEdges) {
      let index = 0;
      for (const group of groups) {
        const bounds = this.bounds.get(group.id);
        if (!bounds) continue;
        const width = bounds.maxX - bounds.minX;
        const depth = bounds.maxZ - bounds.minZ;
        this.transform.position.set(
          (bounds.minX + bounds.maxX) / 2,
          0.026,
          (bounds.minZ + bounds.maxZ) / 2,
        );
        this.transform.scale.set(width, 0.025, depth);
        this.transform.updateMatrix();
        this.tileEdges.setMatrixAt(index, this.transform.matrix);
        this.color.set(group.color).lerp(this.white, 0.72);
        this.tileEdges.setColorAt(index, this.color);
        this.transform.position.y = 0.059;
        this.transform.scale.set(
          Math.max(0.1, width - 0.035),
          0.04,
          Math.max(0.1, depth - 0.035),
        );
        this.transform.updateMatrix();
        this.tiles.setMatrixAt(index, this.transform.matrix);
        this.color.set(group.color).lerp(this.white, 0.955);
        this.tiles.setColorAt(index, this.color);
        index += 1;
      }
      for (const tile of [this.tiles, this.tileEdges]) {
        tile.count = index;
        tile.instanceMatrix.needsUpdate = true;
        if (tile.instanceColor) tile.instanceColor.needsUpdate = true;
      }
    }
    const selected = selectedId
      ? nodes.find((node) => node.id === selectedId)
      : undefined;
    this.selection.visible = !!selected;
    if (selected) {
      const position = positions.get(selected.id) ?? selected.position;
      this.selection.position.set(position.x, 0.095, position.z);
      const selectedKind = nodeVisualKind(selected);
      const scale =
        selectedKind === "broker"
          ? 1.6
          : selectedKind === "group"
            ? 1.55
            : selectedKind === "charger" || selectedKind === "device"
              ? 1.35
              : 1;
      const visualScale = scale * nodeVisualScale(selected);
      this.selection.scale.set(visualScale, visualScale, visualScale);
    }
  }

  nodeForIntersection(intersection: THREE.Intersection): string | null {
    const batch = this.batches.find(
      (candidate) => candidate.mesh === intersection.object,
    );
    return batch && intersection.instanceId !== undefined
      ? (batch.ids[intersection.instanceId] ?? null)
      : null;
  }

  dispose() {
    for (const batch of this.batches) batch.mesh.dispose();
    this.tiles?.dispose();
    this.tileEdges?.dispose();
    for (const geometry of this.geometries) geometry.dispose();
    for (const material of this.materials) material.dispose();
    this.object.clear();
  }
}
