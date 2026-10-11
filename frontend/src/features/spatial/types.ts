import type { SpatialSystemMetadata } from "./systemTypes";

export type Point = { x: number; z: number };
export type CameraPose = {
  position: [number, number, number];
  target: [number, number, number];
  zoom: number;
};
export type SpatialGroup = {
  id: string;
  name: string;
  color: string;
  collapsed: boolean;
  locked: boolean;
};
/** Personal organization is presentation only and can span catalog groups. */
export type SpatialPersonalGroup = {
  id: string;
  name: string;
  color: string;
  memberIds: string[];
};
export type SpatialNode = {
  id: string;
  label: string;
  kind: "broker" | "charger" | "device" | "sensor" | "group";
  brokerId?: string;
  groupId: string;
  position: Point;
  locked: boolean;
  unit: string;
  metric: string;
  baseRate: number;
  color?: string;
  system?: SpatialSystemMetadata;
  catalog?: {
    sourceId: string;
    chargerId?: string;
    sensorKey?: string;
    upstreamTopic?: string;
    valueType?: "number" | "boolean" | "text" | "identifier";
    collectionMode?: "off" | "original" | "sample";
    intervalSeconds?: number;
    category?: string;
    localId?: string;
  };
};
export type SpatialEdge = { id: string; source: string; target: string };
export type Topology = { nodes: SpatialNode[]; edges: SpatialEdge[] };
export type Sample = { timestamp: number; value: number };
export type NodeTelemetry = {
  value: number;
  lastSeen: number;
  received: number;
  rate: number;
  samples: readonly Sample[];
};
export type TelemetryMessage = Sample & { nodeId: string };
export interface SpatialTelemetry {
  getSnapshot(id: string): NodeTelemetry | undefined;
  subscribe(listener: (message: TelemetryMessage) => void): () => void;
}
export type Perspective = {
  id: string;
  name: string;
  camera: CameraPose;
  view?: "isometric" | "top";
};
export type SpatialWorkspace = {
  version: 1;
  layoutMode?: "automatic" | "manual";
  positions: Record<string, Point>;
  locks: Record<string, boolean>;
  memberships: Record<string, string>;
  groups: SpatialGroup[];
  personalGroups?: SpatialPersonalGroup[];
  camera: CameraPose;
  perspectives: Perspective[];
};
export type RenderStats = {
  fps: number;
  drawCalls: number;
  visibleNodes: number;
  particles: number;
};
