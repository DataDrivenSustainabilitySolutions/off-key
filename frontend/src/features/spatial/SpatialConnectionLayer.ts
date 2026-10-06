import * as THREE from "three";
import { curvePoint } from "./sceneGeometry";
import type {
  Point,
  SpatialEdge,
  SpatialGroup,
  SpatialNode,
  TelemetryMessage,
} from "./types";

const SEGMENTS = 18;
const MAX_PARTICLES = 256;
const TRANSIT_MS = 1050;
type Pulse = {
  edge: SpatialEdge | null;
  direction: number;
  started: number;
  color: string;
};

/** A fixed particle pool and one line batch bound the cost of streaming traffic. */
export class SpatialConnectionLayer {
  readonly object = new THREE.Group();
  private readonly lineGeometry = new THREE.BufferGeometry();
  private readonly lineMaterial = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.75,
  });
  private readonly lines = new THREE.LineSegments(
    this.lineGeometry,
    this.lineMaterial,
  );
  private readonly particleGeometry = new THREE.BufferGeometry();
  private readonly particleMaterial = new THREE.PointsMaterial({
    size: 5,
    sizeAttenuation: false,
    vertexColors: true,
    transparent: true,
    opacity: 0.92,
    depthWrite: false,
  });
  private readonly particleMesh = new THREE.Points(
    this.particleGeometry,
    this.particleMaterial,
  );
  private readonly particlePositions = new Float32Array(MAX_PARTICLES * 3);
  private readonly particleColors = new Float32Array(MAX_PARTICLES * 3);
  private readonly pulses: Pulse[] = Array.from(
    { length: MAX_PARTICLES },
    () => ({ edge: null, direction: 1, started: 0, color: "#5b93c6" }),
  );
  private positions: ReadonlyMap<string, Point> = new Map();
  private edges: SpatialEdge[] = [];
  private edgesByNode = new Map<string, SpatialEdge>();
  private colors = new Map<string, string>();
  private allocation = 0;
  private colorDirty = false;
  private nextSlot = 0;
  private budgetAt = 0;
  private budgetUsed = 0;
  private regularBudgetUsed = 0;
  private selectedSource: string | null = null;
  private quality: "balanced" | "economy" = "balanced";
  private readonly vector = new THREE.Vector3();
  private readonly color = new THREE.Color();
  private readonly neutral = new THREE.Color("#c3ccd1");
  activeCount = 0;

  constructor() {
    this.particleGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(this.particlePositions, 3).setUsage(
        THREE.DynamicDrawUsage,
      ),
    );
    this.particleGeometry.setAttribute(
      "color",
      new THREE.BufferAttribute(this.particleColors, 3).setUsage(
        THREE.DynamicDrawUsage,
      ),
    );
    this.particleMesh.frustumCulled = false;
    this.lines.frustumCulled = false;
    this.object.add(this.lines, this.particleMesh);
    this.clearPulses();
  }

  setTopology(
    nodes: SpatialNode[],
    edges: SpatialEdge[],
    groups: SpatialGroup[],
    quality: "balanced" | "economy",
  ) {
    this.edges = edges;
    this.quality = quality;
    this.edgesByNode.clear();
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const groupColors = new Map(groups.map((group) => [group.id, group.color]));
    this.colors = new Map(
      nodes.map((node) => [
        node.id,
        groupColors.get(node.groupId) ?? "#5b93c6",
      ]),
    );
    for (const edge of edges) {
      // Sensor arrivals travel towards their broker, irrespective of edge storage direction.
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!this.edgesByNode.has(edge.source) || target?.kind === "broker")
        this.edgesByNode.set(edge.source, edge);
      if (!this.edgesByNode.has(edge.target) || source?.kind === "broker")
        this.edgesByNode.set(edge.target, edge);
    }
    if (edges.length > this.allocation) {
      this.allocation = Math.max(
        16,
        2 ** Math.ceil(Math.log2(Math.max(1, edges.length))),
      );
      const length = this.allocation * SEGMENTS * 2 * 3;
      this.lineGeometry.setAttribute(
        "position",
        new THREE.BufferAttribute(new Float32Array(length), 3).setUsage(
          THREE.DynamicDrawUsage,
        ),
      );
      this.lineGeometry.setAttribute(
        "color",
        new THREE.BufferAttribute(new Float32Array(length), 3).setUsage(
          THREE.DynamicDrawUsage,
        ),
      );
    }
    this.lineGeometry.setDrawRange(0, edges.length * SEGMENTS * 2);
  }

  updateLines(
    positions: ReadonlyMap<string, Point>,
    selectedId: string | null,
  ) {
    this.positions = positions;
    this.selectedSource = selectedId;
    const positionAttribute = this.lineGeometry.getAttribute("position");
    const colorAttribute = this.lineGeometry.getAttribute("color");
    if (!positionAttribute || !colorAttribute) return;
    let offset = 0;
    for (const edge of this.edges) {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      const selected = edge.source === selectedId || edge.target === selectedId;
      this.color
        .set(this.colors.get(edge.source) ?? "#879aaa")
        .lerp(this.neutral, selected ? 0.15 : 0.84);
      for (let segment = 0; segment < SEGMENTS; segment += 1) {
        for (let endpoint = 0; endpoint < 2; endpoint += 1) {
          if (source && target) {
            curvePoint(
              source,
              target,
              (segment + endpoint) / SEGMENTS,
              this.vector,
            );
            positionAttribute.setXYZ(
              offset,
              this.vector.x,
              this.vector.y,
              this.vector.z,
            );
          } else positionAttribute.setXYZ(offset, 0, -100000, 0);
          colorAttribute.setXYZ(
            offset,
            this.color.r,
            this.color.g,
            this.color.b,
          );
          offset += 1;
        }
      }
    }
    positionAttribute.needsUpdate = true;
    colorAttribute.needsUpdate = true;
  }

  receive(message: TelemetryMessage, now: number) {
    const edge = this.edgesByNode.get(message.nodeId);
    if (
      !edge ||
      !this.positions.has(edge.source) ||
      !this.positions.has(edge.target)
    )
      return false;
    if (now - this.budgetAt >= 1000) {
      this.budgetAt = now;
      this.budgetUsed = 0;
      this.regularBudgetUsed = 0;
    }
    const budget = this.quality === "economy" ? 30 : 80;
    if (this.budgetUsed >= budget) return false;
    // Keep capacity for the inspected object's real arrivals when a large topology saturates the pool.
    const priority =
      edge.source === this.selectedSource ||
      edge.target === this.selectedSource;
    const regularLimit = this.selectedSource
      ? Math.floor(budget * 0.75)
      : budget;
    if (!priority && this.regularBudgetUsed >= regularLimit) return false;
    this.budgetUsed += 1;
    if (!priority) this.regularBudgetUsed += 1;
    const poolSize = this.quality === "economy" ? 128 : MAX_PARTICLES;
    const pulse = this.pulses[this.nextSlot % poolSize];
    this.nextSlot += 1;
    if (!pulse) return false;
    pulse.edge = edge;
    pulse.direction = edge.source === message.nodeId ? 1 : -1;
    pulse.started = now;
    pulse.color = this.colors.get(message.nodeId) ?? "#5b93c6";
    const index = (this.nextSlot - 1) % poolSize;
    this.color.set(pulse.color);
    this.particleColors[index * 3] = this.color.r;
    this.particleColors[index * 3 + 1] = this.color.g;
    this.particleColors[index * 3 + 2] = this.color.b;
    this.colorDirty = true;
    this.activeCount += 1;
    return true;
  }

  updatePulses(now: number, reducedMotion: boolean) {
    let active = 0;
    for (let index = 0; index < this.pulses.length; index += 1) {
      const pulse = this.pulses[index];
      if (!pulse) continue;
      const elapsed = now - pulse.started;
      const source = pulse.edge
        ? this.positions.get(pulse.edge.source)
        : undefined;
      const target = pulse.edge
        ? this.positions.get(pulse.edge.target)
        : undefined;
      if (pulse.edge && source && target && elapsed < TRANSIT_MS) {
        const progress = reducedMotion
          ? pulse.direction === 1
            ? 0
            : 1
          : pulse.direction === 1
            ? elapsed / TRANSIT_MS
            : 1 - elapsed / TRANSIT_MS;
        curvePoint(source, target, progress, this.vector);
        this.particlePositions[index * 3] = this.vector.x;
        this.particlePositions[index * 3 + 1] = reducedMotion
          ? 0.64
          : this.vector.y + 0.035;
        this.particlePositions[index * 3 + 2] = this.vector.z;
        active += 1;
      } else {
        pulse.edge = null;
        this.particlePositions[index * 3 + 1] = -100000;
      }
    }
    this.activeCount = active;
    this.particleGeometry.getAttribute("position").needsUpdate = true;
    if (this.colorDirty) {
      this.particleGeometry.getAttribute("color").needsUpdate = true;
      this.colorDirty = false;
    }
    this.particleMesh.visible = active > 0;
    return active > 0;
  }

  clearPulses() {
    for (let index = 0; index < MAX_PARTICLES; index += 1) {
      const pulse = this.pulses[index];
      if (pulse) pulse.edge = null;
      this.particlePositions[index * 3 + 1] = -100000;
    }
    this.activeCount = 0;
    this.particleMesh.visible = false;
    this.particleGeometry.getAttribute("position").needsUpdate = true;
  }

  dispose() {
    this.lineGeometry.dispose();
    this.lineMaterial.dispose();
    this.particleGeometry.dispose();
    this.particleMaterial.dispose();
    this.object.clear();
  }
}
