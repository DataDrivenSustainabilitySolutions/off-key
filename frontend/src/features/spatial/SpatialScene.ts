import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { SpatialConnectionLayer } from "./SpatialConnectionLayer";
import { SpatialNodeLayer } from "./SpatialNodeLayer";
import { fitCameraDepth, groupBounds } from "./sceneGeometry";
import type {
  CameraPose,
  Point,
  RenderStats,
  SpatialEdge,
  SpatialGroup,
  SpatialNode,
  SpatialTelemetry,
} from "./types";

export type SpatialCanvasProps = {
  nodes: SpatialNode[];
  edges: SpatialEdge[];
  groups: SpatialGroup[];
  selectedId: string | null;
  editMode: boolean;
  camera: CameraPose;
  quality: "balanced" | "economy";
  paused: boolean;
  telemetry: SpatialTelemetry;
  onSelect: (id: string | null) => void;
  onMove: (changes: Record<string, Point>) => void;
  onGroupMove?: (groupId: string, delta: Point) => void;
  onCameraChange: (pose: CameraPose) => void;
  onStats: (stats: RenderStats) => void;
  focusId?: string | null;
  focusRequest?: number;
  fitRequest?: number;
  pulseSources?: Record<string, string>;
  view: "isometric" | "top";
};

type ObjectLabel = { element: HTMLButtonElement; id: string };
type GroupLabel = { element: HTMLSpanElement; id: string };
type Drag = {
  id: string | null;
  groupId: string | null;
  pointerId: number;
  origin: Point;
  initial: Map<string, Point>;
  delta: Point;
};
type FocusAnimation = {
  start: number;
  from: THREE.Vector3;
  to: THREE.Vector3;
  offset: THREE.Vector3;
};

const poseKey = (pose: CameraPose) =>
  [...pose.position, ...pose.target, pose.zoom].join(",");

/** Owns GPU resources and imperative interaction; React changes never recreate the scene. */
export class SpatialScene {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.OrthographicCamera(
    -20,
    20,
    15,
    -15,
    0.1,
    400,
  );
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly nodes = new SpatialNodeLayer();
  private readonly connections = new SpatialConnectionLayer();
  private readonly labels = document.createElement("div");
  private objectLabels: ObjectLabel[] = [];
  private groupLabels: GroupLabel[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private readonly groundPoint = new THREE.Vector3();
  private readonly projected = new THREE.Vector3();
  private readonly positions = new Map<string, Point>();
  private readonly targets = new Map<string, Point>();
  private readonly sourcePositions = new Map<string, Point>();
  private readonly resources: { dispose: () => void }[] = [];
  private readonly resizeObserver: ResizeObserver;
  private readonly motionQuery = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  );
  private unsubscribe: () => void = () => undefined;
  private props: SpatialCanvasProps;
  private drag: Drag | null = null;
  private down: {
    x: number;
    y: number;
    id: string | null;
    pointerId: number;
  } | null = null;
  private hoverId: string | null = null;
  private focusAnimation: FocusAnimation | null = null;
  private pendingFit = false;
  private lastPose = "";
  private width = 1;
  private height = 1;
  private frame: number | null = null;
  private disposed = false;
  private contextLost = false;
  private contextMessage: HTMLDivElement | null = null;
  private dirty = true;
  private geometryDirty = true;
  private lastDraw = 0;
  private frameCount = 0;
  private statsAt = performance.now();
  private readonly statsTimer: ReturnType<typeof setInterval>;

  constructor(
    private readonly host: HTMLDivElement,
    props: SpatialCanvasProps,
  ) {
    this.props = props;
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor("#f9fafb");
    this.renderer.setPixelRatio(
      Math.min(
        window.devicePixelRatio || 1,
        props.quality === "economy" ? 1 : 1.5,
      ),
    );
    this.renderer.domElement.setAttribute(
      "aria-label",
      "Interactive three dimensional telemetry map. Select objects or use the object list.",
    );
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.renderer.domElement.style.touchAction = "none";
    this.host.append(this.renderer.domElement);
    this.scene.background = new THREE.Color("#f9fafb");
    this.scene.add(new THREE.HemisphereLight("#ffffff", "#c1cbd5", 2.3));
    const keyLight = new THREE.DirectionalLight("#ffffff", 2.5);
    keyLight.position.set(8, 24, 14);
    this.scene.add(keyLight);
    const planeGeometry = new THREE.PlaneGeometry(300, 300);
    const planeMaterial = new THREE.MeshStandardMaterial({
      color: "#f9fafb",
      roughness: 1,
    });
    const plane = new THREE.Mesh(planeGeometry, planeMaterial);
    plane.rotation.x = -Math.PI / 2;
    plane.position.y = -0.018;
    this.scene.add(plane);
    const grid = new THREE.GridHelper(160, 160, "#dfe5e9", "#e9edf0");
    grid.position.y = -0.003;
    const gridMaterial = grid.material;
    if (!Array.isArray(gridMaterial)) {
      gridMaterial.transparent = true;
      gridMaterial.opacity = 0.6;
    }
    this.resources.push(
      planeGeometry,
      planeMaterial,
      grid.geometry,
      ...(Array.isArray(gridMaterial) ? gridMaterial : [gridMaterial]),
    );
    this.scene.add(grid, this.nodes.object, this.connections.object);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.screenSpacePanning = false;
    this.controls.minZoom = 0.05;
    this.controls.maxZoom = 5;
    this.controls.minPolarAngle = Math.PI / 12;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.13;
    this.controls.panSpeed = 0.85;
    this.controls.rotateSpeed = 0.45;
    this.controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
    this.controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
    this.controls.touches.ONE = THREE.TOUCH.PAN;
    this.controls.touches.TWO = THREE.TOUCH.DOLLY_ROTATE;
    this.controls.addEventListener("change", this.onControlChange);
    this.controls.addEventListener("start", this.onControlStart);
    this.controls.addEventListener("end", this.saveCamera);
    this.labels.className = "spatial-labels";
    Object.assign(this.labels.style, {
      position: "absolute",
      inset: "0",
      overflow: "hidden",
      pointerEvents: "none",
    });
    this.host.append(this.labels);
    this.renderer.domElement.addEventListener(
      "pointerdown",
      this.onPointerDown,
      true,
    );
    this.renderer.domElement.addEventListener(
      "pointermove",
      this.onPointerMove,
    );
    this.renderer.domElement.addEventListener("pointerup", this.onPointerUp);
    this.renderer.domElement.addEventListener(
      "pointercancel",
      this.onPointerCancel,
    );
    this.renderer.domElement.addEventListener(
      "contextmenu",
      this.onContextMenu,
    );
    this.renderer.domElement.addEventListener(
      "webglcontextlost",
      this.onContextLost,
    );
    this.renderer.domElement.addEventListener(
      "webglcontextrestored",
      this.onContextRestored,
    );
    document.addEventListener("visibilitychange", this.onVisibility);
    this.motionQuery.addEventListener("change", this.onMotionPreference);
    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(this.host);
    this.resize();
    this.configureInteraction();
    this.applyCamera(props.camera);
    this.syncTopology();
    this.subscribeTelemetry();
    this.configureInteraction();
    this.statsTimer = setInterval(this.reportStats, 1000);
    this.pendingFit = (props.fitRequest ?? 0) > 0;
    this.schedule();
  }

  update(props: SpatialCanvasProps) {
    const previous = this.props;
    this.props = props;
    const topologyChanged =
      previous.nodes !== props.nodes ||
      previous.edges !== props.edges ||
      previous.groups !== props.groups;
    if (topologyChanged) this.syncTopology();
    if (previous.telemetry !== props.telemetry) this.subscribeTelemetry();
    if (previous.quality !== props.quality) {
      this.renderer.setPixelRatio(
        Math.min(
          window.devicePixelRatio || 1,
          props.quality === "economy" ? 1 : 1.5,
        ),
      );
      this.renderer.setSize(this.width, this.height, false);
      this.connections.setTopology(
        props.nodes,
        props.edges,
        props.groups,
        props.quality,
      );
      this.invalidate(true);
    }
    if (previous.paused !== props.paused && props.paused) {
      this.connections.clearPulses();
      this.invalidate();
    }
    if (previous.editMode !== props.editMode || previous.view !== props.view)
      this.configureInteraction();
    const externalCameraChanged = poseKey(props.camera) !== this.lastPose;
    if (externalCameraChanged) this.applyCamera(props.camera);
    if (previous.view !== props.view && !externalCameraChanged)
      this.setView(props.view);
    if (previous.selectedId !== props.selectedId) {
      this.rebuildLabels();
      this.invalidate(true);
    }
    if (
      props.focusId &&
      (props.focusId !== previous.focusId ||
        props.focusRequest !== previous.focusRequest)
    )
      this.focus(props.focusId);
    if (props.fitRequest !== previous.fitRequest) this.fit();
  }

  private syncTopology() {
    const alive = new Set(this.props.nodes.map((node) => node.id));
    for (const id of this.positions.keys()) {
      if (!alive.has(id)) {
        this.positions.delete(id);
        this.targets.delete(id);
        this.sourcePositions.delete(id);
      }
    }
    for (const node of this.props.nodes) {
      const previous = this.sourcePositions.get(node.id);
      if (!this.positions.has(node.id))
        this.positions.set(node.id, { ...node.position });
      if (
        !previous ||
        previous.x !== node.position.x ||
        previous.z !== node.position.z
      ) {
        this.targets.set(node.id, { ...node.position });
        this.sourcePositions.set(node.id, { ...node.position });
      }
    }
    this.connections.setTopology(
      this.props.nodes,
      this.props.edges,
      this.props.groups,
      this.props.quality,
    );
    this.rebuildLabels();
    this.invalidate(true);
  }

  private subscribeTelemetry() {
    this.unsubscribe();
    this.unsubscribe = this.props.telemetry.subscribe((message) => {
      if (
        this.props.paused ||
        document.hidden ||
        this.disposed ||
        this.contextLost
      )
        return;
      const visibleSource = this.props.pulseSources?.[message.nodeId];
      const arrival = visibleSource
        ? { ...message, nodeId: visibleSource }
        : message;
      if (this.connections.receive(arrival, performance.now())) this.schedule();
    });
  }

  private configureInteraction() {
    this.controls.enableRotate =
      !this.props.editMode && this.props.view !== "top";
    this.controls.minPolarAngle = this.props.view === "top" ? 0 : Math.PI / 12;
    this.renderer.domElement.style.cursor = this.props.editMode
      ? "grab"
      : "default";
  }

  private applyCamera(pose: CameraPose) {
    this.focusAnimation = null;
    this.lastPose = poseKey(pose);
    this.camera.position.fromArray(pose.position);
    this.camera.zoom = Math.max(0.05, Math.min(5, pose.zoom));
    this.controls.target.fromArray(pose.target);
    this.camera.far = Math.max(
      400,
      this.camera.position.distanceTo(this.controls.target) * 3,
    );
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.invalidate(true);
  }

  private setView(view: "isometric" | "top") {
    const target = this.controls.target;
    const distance = Math.max(20, this.camera.position.distanceTo(target));
    if (view === "top")
      this.camera.position.set(target.x, target.y + distance, target.z + 0.01);
    else
      this.camera.position.set(
        target.x + distance * 0.62,
        target.y + distance * 0.55,
        target.z + distance * 0.62,
      );
    // A top view is intentionally fixed to avoid disorienting camera roll.
    this.controls.minPolarAngle = view === "top" ? 0 : Math.PI / 12;
    this.controls.update();
    this.saveCamera();
    this.invalidate(true);
  }

  private focus(id: string) {
    const position = this.positions.get(id);
    if (!position) return;
    this.focusAnimation = {
      start: performance.now(),
      from: this.controls.target.clone(),
      to: new THREE.Vector3(position.x, 0, position.z),
      offset: this.camera.position.clone().sub(this.controls.target),
    };
    this.schedule();
  }

  private fit() {
    this.focusAnimation = null;
    const groups = groupBounds(this.props.nodes, this.targets);
    if (!groups.size) return;
    let minX = Infinity,
      maxX = -Infinity,
      minZ = Infinity,
      maxZ = -Infinity;
    for (const bounds of groups.values()) {
      minX = Math.min(minX, bounds.minX);
      maxX = Math.max(maxX, bounds.maxX);
      minZ = Math.min(minZ, bounds.minZ);
      maxZ = Math.max(maxZ, bounds.maxZ);
    }
    const offset = this.camera.position.clone().sub(this.controls.target);
    if (offset.lengthSq() < 1) offset.set(22, 28, 30);
    if (this.props.view === "top") offset.set(0, offset.length(), 0.01);
    const depth = fitCameraDepth({ minX, maxX, minZ, maxZ }, offset.length());
    offset.normalize().multiplyScalar(depth.distance);
    this.camera.far = depth.far;
    this.controls.target.set((minX + maxX) / 2, 0, (minZ + maxZ) / 2);
    this.camera.position.copy(this.controls.target).add(offset);
    this.camera.zoom = 1;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.camera.updateMatrixWorld();
    let extentX = 0,
      extentY = 0;
    for (const x of [minX, maxX])
      for (const z of [minZ, maxZ])
        for (const y of [0, 1.25]) {
          this.projected.set(x, y, z).project(this.camera);
          extentX = Math.max(extentX, Math.abs(this.projected.x));
          extentY = Math.max(extentY, Math.abs(this.projected.y));
        }
    // Leave space for the overlaid header, labels and bottom navigation toolbar.
    const availableX = Math.max(0.3, 1 - 80 / this.width);
    const availableY = Math.max(0.25, 1 - 230 / this.height);
    this.camera.zoom = Math.max(
      0.05,
      Math.min(
        3,
        availableX / Math.max(0.05, extentX),
        availableY / Math.max(0.05, extentY),
      ),
    );
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.saveCamera();
    this.invalidate(true);
  }

  private saveCamera = () => {
    if (this.disposed) return;
    const pose: CameraPose = {
      position: this.camera.position.toArray() as [number, number, number],
      target: this.controls.target.toArray() as [number, number, number],
      zoom: this.camera.zoom,
    };
    this.lastPose = poseKey(pose);
    this.props.onCameraChange(pose);
  };

  private onControlChange = () => this.invalidate(true);
  private onControlStart = () => {
    this.focusAnimation = null;
  };
  private onMotionPreference = () => this.invalidate();
  private onContextMenu = (event: Event) => event.preventDefault();

  private resize = () => {
    const { width, height } = this.host.getBoundingClientRect();
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
    this.renderer.setSize(this.width, this.height, false);
    const aspect = this.width / this.height;
    // Keep the first overview legible in a tall/narrow stage without changing saved zoom.
    const span = Math.max(26, 40 / aspect);
    this.camera.left = (-span * aspect) / 2;
    this.camera.right = (span * aspect) / 2;
    this.camera.top = span / 2;
    this.camera.bottom = -span / 2;
    this.camera.updateProjectionMatrix();
    this.invalidate(true);
  };

  private ray(event: PointerEvent) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster;
  }

  private pick(event: PointerEvent) {
    const hit = this.ray(event).intersectObjects(
      this.nodes.pickables,
      false,
    )[0];
    return hit ? this.nodes.nodeForIntersection(hit) : null;
  }

  private planePosition(event: PointerEvent) {
    const hit = this.ray(event).ray.intersectPlane(
      this.ground,
      this.groundPoint,
    );
    return hit ? { x: hit.x, z: hit.z } : null;
  }

  private onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return;
    const id = this.pick(event);
    this.down = {
      x: event.clientX,
      y: event.clientY,
      id,
      pointerId: event.pointerId,
    };
    if (!this.props.editMode) return;
    const position = this.planePosition(event);
    if (!position) return;
    const node = id
      ? this.props.nodes.find((candidate) => candidate.id === id)
      : undefined;
    const group = node
      ? this.props.groups.find((candidate) => candidate.id === node.groupId)
      : undefined;
    if (node && (node.locked || group?.locked)) return;
    let groupId: string | null =
      node?.kind === "group" && this.props.onGroupMove ? node.groupId : null;
    if (!node && this.props.onGroupMove) {
      for (const candidate of this.props.groups) {
        const bounds = this.nodes.bounds.get(candidate.id);
        if (
          bounds &&
          !candidate.locked &&
          position.x >= bounds.minX &&
          position.x <= bounds.maxX &&
          position.z >= bounds.minZ &&
          position.z <= bounds.maxZ
        ) {
          groupId = candidate.id;
          break;
        }
      }
    }
    if (!node && !groupId) return;
    const initial = new Map<string, Point>();
    for (const candidate of this.props.nodes) {
      if (
        candidate.id === id ||
        (groupId && candidate.groupId === groupId && !candidate.locked)
      ) {
        const current = this.positions.get(candidate.id);
        if (current) initial.set(candidate.id, { ...current });
      }
    }
    this.drag = {
      id,
      groupId,
      pointerId: event.pointerId,
      origin: position,
      initial,
      delta: { x: 0, z: 0 },
    };
    this.controls.enabled = false;
    this.renderer.domElement.setPointerCapture(event.pointerId);
    this.renderer.domElement.style.cursor = "grabbing";
    event.preventDefault();
    event.stopImmediatePropagation();
    if (id) this.props.onSelect(id);
  };

  private onPointerMove = (event: PointerEvent) => {
    if (this.drag && this.drag.pointerId === event.pointerId) {
      const next = this.planePosition(event);
      if (!next) return;
      const delta = {
        x: next.x - this.drag.origin.x,
        z: next.z - this.drag.origin.z,
      };
      this.drag.delta = delta;
      for (const [id, origin] of this.drag.initial) {
        const nextPosition = {
          x: origin.x + Math.round(delta.x * 4) / 4,
          z: origin.z + Math.round(delta.z * 4) / 4,
        };
        this.positions.set(id, nextPosition);
        this.targets.set(id, { ...nextPosition });
      }
      this.invalidate(true);
      return;
    }
    if (event.buttons !== 0) return;
    const id = this.pick(event);
    if (id !== this.hoverId) {
      this.hoverId = id;
      this.rebuildLabels();
      this.invalidate();
    }
    const node = id
      ? this.props.nodes.find((candidate) => candidate.id === id)
      : undefined;
    const group = node
      ? this.props.groups.find((candidate) => candidate.id === node.groupId)
      : undefined;
    this.renderer.domElement.style.cursor = node
      ? this.props.editMode
        ? node.locked || group?.locked
          ? "not-allowed"
          : "grab"
        : "pointer"
      : this.props.editMode
        ? "grab"
        : "default";
  };

  private onPointerUp = (event: PointerEvent) => {
    if (this.drag && this.drag.pointerId === event.pointerId) {
      const drag = this.drag;
      this.drag = null;
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(event.pointerId))
        this.renderer.domElement.releasePointerCapture(event.pointerId);
      const moved = Math.hypot(drag.delta.x, drag.delta.z) > 0.1;
      if (moved && drag.groupId && this.props.onGroupMove) {
        const first = drag.initial.entries().next().value as
          [string, Point] | undefined;
        const actual = first ? this.positions.get(first[0]) : undefined;
        if (first && actual)
          this.props.onGroupMove(drag.groupId, {
            x: actual.x - first[1].x,
            z: actual.z - first[1].z,
          });
      } else if (moved && drag.id) {
        const position = this.positions.get(drag.id);
        if (position) this.props.onMove({ [drag.id]: { ...position } });
      }
      this.configureInteraction();
    } else if (
      this.down &&
      this.down.pointerId === event.pointerId &&
      Math.hypot(event.clientX - this.down.x, event.clientY - this.down.y) < 5
    )
      this.props.onSelect(this.down.id);
    this.down = null;
  };

  private onPointerCancel = (event: PointerEvent) => {
    if (this.drag?.pointerId === event.pointerId) {
      for (const [id, position] of this.drag.initial) {
        this.positions.set(id, { ...position });
        this.targets.set(id, { ...position });
      }
      this.drag = null;
      this.controls.enabled = true;
      this.configureInteraction();
      this.invalidate(true);
    }
    this.down = null;
  };

  private rebuildLabels() {
    this.labels.replaceChildren();
    this.objectLabels = [];
    this.groupLabels = [];
    const important = this.props.nodes.filter(
      (node) =>
        node.kind !== "sensor" ||
        node.id === this.props.selectedId ||
        node.id === this.hoverId,
    );
    const prioritized = important.sort(
      (a, b) =>
        Number(b.id === this.props.selectedId || b.id === this.hoverId) -
        Number(a.id === this.props.selectedId || a.id === this.hoverId),
    );
    for (const node of prioritized.slice(0, 40)) {
      const label = document.createElement("button");
      label.type = "button";
      label.className = `spatial-object-label${node.id === this.props.selectedId ? " selected" : ""}`;
      label.textContent = node.label;
      label.title = `${node.label} · ${node.kind}${node.locked ? " · locked" : ""}`;
      Object.assign(label.style, {
        position: "absolute",
        display: "none",
        left: "0",
        top: "0",
        maxWidth: "190px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        pointerEvents: "auto",
        border: "1px solid rgba(197,206,214,.65)",
        borderRadius: "7px",
        background:
          node.id === this.props.selectedId ? "#fff" : "rgba(255,255,255,.9)",
        color: "#425264",
        padding: "5px 9px",
        font: "500 11px/1.3 system-ui, sans-serif",
        boxShadow: "0 2px 5px rgba(25,40,57,.025)",
        cursor: "pointer",
      });
      if (node.id === this.props.selectedId) {
        label.style.borderColor = "#7d96ac";
        label.style.color = "#1b344b";
      }
      label.addEventListener("click", (event) => {
        event.stopPropagation();
        this.props.onSelect(node.id);
      });
      this.labels.append(label);
      this.objectLabels.push({ element: label, id: node.id });
    }
    for (const group of this.props.groups.slice(0, 24)) {
      if (
        this.props.nodes.some(
          (node) => node.kind === "group" && node.groupId === group.id,
        )
      )
        continue;
      const label = document.createElement("span");
      label.className = "spatial-group-label";
      label.textContent = `${group.name}${group.locked ? " · locked" : ""}`;
      Object.assign(label.style, {
        position: "absolute",
        display: "none",
        left: "0",
        top: "0",
        color: "#758392",
        font: "600 10px/1.4 system-ui, sans-serif",
        letterSpacing: "0.07em",
        textTransform: "uppercase",
        whiteSpace: "nowrap",
      });
      this.labels.append(label);
      this.groupLabels.push({ element: label, id: group.id });
    }
  }

  private positionLabel(
    element: HTMLElement,
    x: number,
    y: number,
    z: number,
    offset: number,
  ) {
    this.projected.set(x, y, z).project(this.camera);
    const screenX = (this.projected.x * 0.5 + 0.5) * this.width;
    const screenY = (-this.projected.y * 0.5 + 0.5) * this.height + offset;
    const visible =
      this.projected.z >= -1 &&
      this.projected.z <= 1 &&
      screenX > 24 &&
      screenX < this.width - 24 &&
      screenY > 10 &&
      screenY < this.height - 10;
    element.style.display = visible ? "" : "none";
    if (visible)
      element.style.transform = `translate(${screenX.toFixed(1)}px,${screenY.toFixed(1)}px) translate(-50%,-100%)`;
  }

  private updateLabels() {
    for (const label of this.objectLabels) {
      const position = this.positions.get(label.id);
      const node = this.props.nodes.find(
        (candidate) => candidate.id === label.id,
      );
      if (position && node)
        this.positionLabel(
          label.element,
          position.x,
          node.kind === "broker" ? 1 : 0.6,
          position.z,
          -10,
        );
      else label.element.style.display = "none";
    }
    for (const label of this.groupLabels) {
      const bounds = this.nodes.bounds.get(label.id);
      if (bounds)
        this.positionLabel(
          label.element,
          (bounds.minX + bounds.maxX) / 2,
          0.1,
          bounds.maxZ + 0.26,
          18,
        );
      else label.element.style.display = "none";
    }
  }

  private invalidate(geometry = false) {
    this.dirty = true;
    this.geometryDirty ||= geometry;
    this.schedule();
  }

  private schedule() {
    if (
      this.disposed ||
      document.hidden ||
      this.contextLost ||
      this.frame !== null
    )
      return;
    this.frame = requestAnimationFrame(this.tick);
  }

  private tick = (now: number) => {
    this.frame = null;
    if (this.disposed || document.hidden || this.contextLost) return;
    if (this.pendingFit) {
      this.pendingFit = false;
      this.fit();
    }
    const interval = 1000 / (this.props.quality === "economy" ? 30 : 60);
    if (now - this.lastDraw < interval - 1) {
      this.schedule();
      return;
    }
    const elapsed = this.lastDraw
      ? Math.min(0.1, (now - this.lastDraw) / 1000)
      : 0.017;
    let moving = false;
    const blend = this.motionQuery.matches ? 1 : 1 - Math.exp(-elapsed * 18);
    for (const [id, target] of this.targets) {
      const current = this.positions.get(id);
      if (!current) continue;
      const distance =
        Math.abs(current.x - target.x) + Math.abs(current.z - target.z);
      if (distance > 0.005) {
        current.x += (target.x - current.x) * blend;
        current.z += (target.z - current.z) * blend;
        moving = true;
      } else if (distance > 0) {
        current.x = target.x;
        current.z = target.z;
        this.geometryDirty = true;
      }
    }
    if (this.focusAnimation) {
      const focus = this.focusAnimation;
      const progress = this.motionQuery.matches
        ? 1
        : Math.min(1, (now - focus.start) / 360);
      const eased = 1 - (1 - progress) ** 3;
      this.controls.target.lerpVectors(focus.from, focus.to, eased);
      this.camera.position.copy(this.controls.target).add(focus.offset);
      this.controls.update();
      if (progress === 1) {
        this.focusAnimation = null;
        this.saveCamera();
      }
      this.geometryDirty = true;
      this.dirty = true;
    }
    if (this.geometryDirty || moving) {
      this.camera.updateMatrixWorld();
      this.nodes.update(
        this.props.nodes,
        this.positions,
        this.props.groups,
        this.props.selectedId,
        this.camera,
      );
      this.connections.updateLines(this.positions, this.props.selectedId);
      this.geometryDirty = false;
      this.dirty = true;
    }
    const hadParticles = this.connections.activeCount > 0;
    const activeParticles = hadParticles
      ? this.connections.updatePulses(now, this.motionQuery.matches)
      : false;
    if (this.dirty || activeParticles || hadParticles) {
      this.renderer.render(this.scene, this.camera);
      this.updateLabels();
      this.frameCount += 1;
      this.lastDraw = now;
      this.dirty = false;
    }
    if (activeParticles || moving || this.focusAnimation) this.schedule();
  };

  private reportStats = () => {
    const now = performance.now();
    const fps =
      document.hidden || this.contextLost
        ? 0
        : Math.round(
            (this.frameCount * 1000) / Math.max(1, now - this.statsAt),
          );
    this.props.onStats({
      fps,
      drawCalls: this.renderer.info.render.calls,
      visibleNodes: this.nodes.visibleCount,
      particles: this.connections.activeCount,
    });
    this.frameCount = 0;
    this.statsAt = now;
  };

  private onVisibility = () => {
    if (document.hidden) {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null;
      this.connections.clearPulses();
      this.saveCamera();
    } else {
      this.lastDraw = 0;
      this.invalidate(true);
    }
  };

  private onContextLost = (event: Event) => {
    event.preventDefault();
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    this.contextLost = true;
    this.connections.clearPulses();
    this.host.dataset.webglLost = "true";
    const message = document.createElement("div");
    message.className = "spatial-webgl-fallback";
    message.setAttribute("role", "status");
    message.textContent =
      "The graphics connection paused. Your layout is safe; the object list and charts remain available.";
    Object.assign(message.style, {
      position: "absolute",
      top: "24px",
      left: "50%",
      transform: "translateX(-50%)",
      maxWidth: "420px",
      padding: "12px 18px",
      background: "#fff",
      borderRadius: "12px",
      color: "#59687a",
      font: "13px/1.5 system-ui",
    });
    this.host.append(message);
    this.contextMessage = message;
  };

  private onContextRestored = () => {
    delete this.host.dataset.webglLost;
    this.contextLost = false;
    this.contextMessage?.remove();
    this.contextMessage = null;
    this.lastDraw = 0;
    this.invalidate(true);
  };

  dispose() {
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    clearInterval(this.statsTimer);
    this.unsubscribe();
    this.resizeObserver.disconnect();
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.motionQuery.removeEventListener("change", this.onMotionPreference);
    this.renderer.domElement.removeEventListener(
      "pointerdown",
      this.onPointerDown,
      true,
    );
    this.renderer.domElement.removeEventListener(
      "pointermove",
      this.onPointerMove,
    );
    this.renderer.domElement.removeEventListener("pointerup", this.onPointerUp);
    this.renderer.domElement.removeEventListener(
      "pointercancel",
      this.onPointerCancel,
    );
    this.renderer.domElement.removeEventListener(
      "contextmenu",
      this.onContextMenu,
    );
    this.renderer.domElement.removeEventListener(
      "webglcontextlost",
      this.onContextLost,
    );
    this.renderer.domElement.removeEventListener(
      "webglcontextrestored",
      this.onContextRestored,
    );
    this.controls.removeEventListener("change", this.onControlChange);
    this.controls.removeEventListener("start", this.onControlStart);
    this.controls.removeEventListener("end", this.saveCamera);
    this.controls.dispose();
    this.nodes.dispose();
    this.connections.dispose();
    for (const resource of this.resources) resource.dispose();
    this.scene.clear();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.remove();
    this.contextMessage?.remove();
  }
}
