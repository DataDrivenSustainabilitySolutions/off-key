import type { MqttClient } from "mqtt";
import { TelemetryRecord } from "./telemetry";
import type {
  NodeTelemetry,
  SpatialNode,
  SpatialTelemetry,
  TelemetryMessage,
  Topology,
} from "./types";

export const HSL_TOPIC = "/hfp/v2/journey/ongoing/vp/tram/#";
const HSL_BROKER: SpatialNode = {
  id: "hsl:broker",
  label: "HSL public MQTT",
  kind: "broker",
  groupId: "environment",
  position: { x: 0, z: 0 },
  locked: true,
  unit: "msg/s",
  metric: "Observed arrivals",
  baseRate: 0,
};
export const HSL_INITIAL_TOPOLOGY: Topology = {
  nodes: [HSL_BROKER],
  edges: [],
};
const MAX_VEHICLES = 24;
let mqttModule: Promise<typeof import("mqtt")> | undefined;

export type HslObservation = {
  id: string;
  label: string;
  timestamp: number;
  value: number;
};

/** HFP's public VP payload: speed is m/s; charts display km/h. No coordinates are stored. */
export function parseHslPayload(
  payload: string | Uint8Array,
  arrivalTime: number,
): HslObservation | undefined {
  if (payload.length > 65_536 || !Number.isFinite(arrivalTime)) return;
  let input: unknown;
  try {
    input = JSON.parse(
      typeof payload === "string" ? payload : new TextDecoder().decode(payload),
    );
  } catch {
    return;
  }
  if (!input || typeof input !== "object" || !("VP" in input)) return;
  const vp = (input as { VP: unknown }).VP;
  if (!vp || typeof vp !== "object") return;
  const row = vp as Record<string, unknown>;
  if (
    typeof row.oper !== "number" ||
    !Number.isSafeInteger(row.oper) ||
    row.oper < 0 ||
    row.oper > 9999
  )
    return;
  if (
    typeof row.veh !== "number" ||
    !Number.isSafeInteger(row.veh) ||
    row.veh < 0 ||
    row.veh > 99999
  )
    return;
  if (
    typeof row.spd !== "number" ||
    !Number.isFinite(row.spd) ||
    row.spd < 0 ||
    row.spd > 150
  )
    return;
  const parsed = typeof row.tst === "string" ? Date.parse(row.tst) : NaN;
  // A malformed, future, or implausibly old clock cannot corrupt the chart axis.
  const timestamp =
    Number.isFinite(parsed) &&
    parsed <= arrivalTime + 60_000 &&
    parsed >= arrivalTime - 86_400_000
      ? parsed
      : arrivalTime;
  const route =
    typeof row.desi === "string" ? row.desi.trim().slice(0, 20) : "";
  return {
    id: `hsl:${row.oper}:${row.veh}`,
    label: `Tram ${row.veh}${route ? ` · line ${route}` : ""}`,
    timestamp,
    value: row.spd * 3.6,
  };
}

type LiveSourceOptions = {
  onTopology: (topology: Topology) => void;
  onStatus: (status: string) => void;
};

/** Explicit opt-in to one public feed. The entire draft stays client-side and bounded. */
export class HslTelemetry implements SpatialTelemetry {
  private readonly records = new Map<string, TelemetryRecord>([
    [HSL_BROKER.id, new TelemetryRecord()],
  ]);
  private readonly vehicles = new Map<string, SpatialNode>();
  private readonly listeners = new Set<(message: TelemetryMessage) => void>();
  private client: MqttClient | undefined;
  private generation = 0;
  private disposed = false;
  private paused = false;
  private started = false;
  private topologyTimer: ReturnType<typeof setTimeout> | undefined;
  private lastTopology = 0;
  private lastBrokerSample = 0;
  private status = "";

  constructor(private readonly options: LiveSourceOptions) {}

  getSnapshot(id: string): NodeTelemetry | undefined {
    return this.records.get(id);
  }

  subscribe(listener: (message: TelemetryMessage) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    if (this.started && !this.disposed) return;
    this.disposed = false;
    this.started = true;
    document.addEventListener("visibilitychange", this.updateRunning);
    this.lastTopology = Date.now();
    this.publishTopology();
    this.updateRunning();
  }

  setPaused(paused: boolean): void {
    if (this.disposed || this.paused === paused) return;
    this.paused = paused;
    this.updateRunning();
  }

  dispose(): void {
    this.disposed = true;
    this.started = false;
    this.closeClient();
    if (this.topologyTimer !== undefined) clearTimeout(this.topologyTimer);
    this.topologyTimer = undefined;
    document.removeEventListener("visibilitychange", this.updateRunning);
    this.listeners.clear();
  }

  private closeClient(): void {
    this.generation++;
    const client = this.client;
    this.client = undefined;
    if (client) {
      client.removeAllListeners();
      // MQTT.js can emit a delayed CONNACK error after end(true) while connecting.
      // Detach all application callbacks, but keep that SDK error harmless.
      client.on("error", () => {});
      client.end(true);
    }
  }

  private updateRunning = (): void => {
    this.closeClient();
    if (!this.started || this.disposed) return;
    if (this.paused || document.hidden) {
      this.setStatus(this.paused ? "Paused" : "Suspended while tab is hidden");
      return;
    }
    void this.connect();
  };

  private async connect(): Promise<void> {
    const generation = this.generation;
    this.setStatus("Connecting to HSL public MQTT…");
    try {
      // Share the lazy module load during React's mount/cleanup/remount cycle.
      const imported = await (mqttModule ??= import("mqtt"));
      if (
        this.disposed ||
        this.paused ||
        document.hidden ||
        generation !== this.generation
      )
        return;
      // The browser ESM bundle exports its API only as default, whereas Node
      // and some bundler versions also expose named exports.
      const mqtt = imported.default ?? imported;
      const client = mqtt.connect("wss://mqtt.hsl.fi:443/", {
        clean: true,
        keepalive: 30,
        reconnectPeriod: 30_000,
        connectTimeout: 10_000,
        resubscribe: false,
        queueQoSZero: false,
      });
      this.client = client;
      const active = (): boolean =>
        !this.disposed &&
        !this.paused &&
        !document.hidden &&
        this.client === client;
      client.on("connect", () => {
        if (!active()) return;
        this.setStatus("Connected · waiting for live tram measurements");
        client.subscribe(HSL_TOPIC, { qos: 0 }, (error) => {
          if (active() && error)
            this.setStatus("HSL subscription failed · retry by reconnecting");
        });
      });
      client.on("message", (topic, payload, packet) => {
        if (!active() || !topic.startsWith("/hfp/v2/journey/ongoing/vp/tram/"))
          return;
        this.onMessage(payload, packet.retain === true);
      });
      client.on("reconnect", () => {
        if (active())
          this.setStatus("Reconnecting to HSL · retry every 30 seconds");
      });
      client.on("close", () => {
        if (active())
          this.setStatus("HSL disconnected · retrying in 30 seconds");
      });
      client.on("error", () => {
        if (active())
          this.setStatus("HSL connection failed · retrying in 30 seconds");
      });
    } catch {
      if (!this.disposed && generation === this.generation)
        this.setStatus(
          "Live source unavailable · simulation remains available",
        );
    }
  }

  private onMessage(payload: Uint8Array, retained: boolean): void {
    const now = Date.now();
    const observation = parseHslPayload(payload, now);
    if (!observation) return;
    let record = this.records.get(observation.id);
    if (!record) {
      if (this.vehicles.size >= MAX_VEHICLES) return;
      const slot = this.vehicles.size;
      const angle = ((slot % 8) * Math.PI) / 4;
      const radius = 8 + Math.floor(slot / 8) * 5;
      this.vehicles.set(observation.id, {
        id: observation.id,
        label: observation.label,
        kind: "sensor",
        brokerId: HSL_BROKER.id,
        groupId: "environment",
        position: { x: Math.cos(angle) * radius, z: Math.sin(angle) * radius },
        locked: false,
        unit: "km/h",
        metric: "Speed",
        baseRate: 1,
      });
      record = new TelemetryRecord();
      this.records.set(observation.id, record);
      this.queueTopology();
    } else {
      const node = this.vehicles.get(observation.id);
      if (node && node.label !== observation.label) {
        this.vehicles.set(observation.id, {
          ...node,
          label: observation.label,
        });
        this.queueTopology();
      }
    }
    record.receive(
      { timestamp: observation.timestamp, value: observation.value },
      now,
      retained,
    );
    if (retained) return;
    const broker = this.records.get(HSL_BROKER.id)!;
    broker.receiveAggregate(now, now - this.lastBrokerSample >= 1_000);
    if (now - this.lastBrokerSample >= 1_000) this.lastBrokerSample = now;
    this.setStatus("Live · HSL public MQTT · up to 24 trams");
    const message: TelemetryMessage = {
      nodeId: observation.id,
      timestamp: now,
      value: observation.value,
    };
    for (const listener of this.listeners) listener(message);
  }

  private queueTopology(): void {
    if (this.topologyTimer !== undefined) return;
    const wait = Math.max(0, 1_000 - (Date.now() - this.lastTopology));
    this.topologyTimer = setTimeout(() => {
      this.topologyTimer = undefined;
      if (this.disposed) return;
      this.lastTopology = Date.now();
      this.publishTopology();
    }, wait);
  }

  private publishTopology(): void {
    // Previously assigned positions never shift when another tram appears.
    const sensors = [...this.vehicles.values()].sort((a, b) =>
      a.id.localeCompare(b.id),
    );
    this.options.onTopology({
      nodes: [HSL_BROKER, ...sensors],
      edges: sensors.map((node) => ({
        id: `${node.id}>${HSL_BROKER.id}`,
        source: node.id,
        target: HSL_BROKER.id,
      })),
    });
  }

  private setStatus(status: string): void {
    if (this.status === status || this.disposed) return;
    this.status = status;
    this.options.onStatus(status);
  }
}
