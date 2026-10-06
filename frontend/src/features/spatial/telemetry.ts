import type {
  NodeTelemetry,
  Sample,
  SpatialNode,
  SpatialTelemetry,
  TelemetryMessage,
} from "./types";

export const SAMPLE_LIMIT = 360;
const RATE_WINDOW_SECONDS = 10;

/** Fixed memory per source. Chart snapshots are materialized only when requested. */
class SampleRing {
  private readonly rows: Array<Sample | undefined> = new Array(SAMPLE_LIMIT);
  private cursor = 0;
  private length = 0;
  private cached: readonly Sample[] | undefined;

  push(sample: Sample): void {
    this.rows[this.cursor] = sample;
    this.cursor = (this.cursor + 1) % SAMPLE_LIMIT;
    this.length = Math.min(SAMPLE_LIMIT, this.length + 1);
    this.cached = undefined;
  }

  snapshot(): readonly Sample[] {
    if (this.cached) return this.cached;
    const ordered: Sample[] = [];
    const start = (this.cursor - this.length + SAMPLE_LIMIT) % SAMPLE_LIMIT;
    for (let i = 0; i < this.length; i++) {
      const row = this.rows[(start + i) % SAMPLE_LIMIT];
      if (row) ordered.push(row);
    }
    this.cached = ordered;
    return ordered;
  }
}

/** Eleven one-second buckets keep arrival-rate accounting bounded, even at scale. */
class ArrivalRate {
  private readonly buckets = Array.from(
    { length: RATE_WINDOW_SECONDS + 1 },
    () => ({ second: -1, count: 0 }),
  );
  private firstArrival: number | undefined;

  add(timestamp: number): void {
    this.firstArrival ??= timestamp;
    const second = Math.floor(timestamp / 1_000);
    const bucket = this.buckets[second % this.buckets.length]!;
    if (bucket.second !== second) {
      bucket.second = second;
      bucket.count = 0;
    }
    bucket.count++;
  }

  value(now: number): number {
    if (this.firstArrival === undefined) return 0;
    const currentSecond = Math.floor(now / 1_000);
    let count = 0;
    for (const bucket of this.buckets) {
      if (
        bucket.second > currentSecond - RATE_WINDOW_SECONDS &&
        bucket.second <= currentSecond
      )
        count += bucket.count;
    }
    return (
      count /
      Math.min(
        RATE_WINDOW_SECONDS,
        Math.max(1, (now - this.firstArrival) / 1_000),
      )
    );
  }
}

/** Returned records stay stable; reading a value never allocates a history array. */
export class TelemetryRecord implements NodeTelemetry {
  value = 0;
  lastSeen = 0;
  received = 0;
  private readonly history = new SampleRing();
  private readonly arrivals = new ArrivalRate();

  get rate(): number {
    return this.arrivals.value(Date.now());
  }
  get samples(): readonly Sample[] {
    return this.history.snapshot();
  }

  seed(sample: Sample): void {
    this.value = sample.value;
    this.history.push(sample);
  }

  receive(sample: Sample, arrivalTime: number, retained = false): void {
    this.value = sample.value;
    this.history.push(sample);
    if (!retained) {
      this.lastSeen = arrivalTime;
      this.received++;
      this.arrivals.add(arrivalTime);
    }
  }

  receiveAggregate(arrivalTime: number, recordHistory: boolean): void {
    this.lastSeen = arrivalTime;
    this.received++;
    this.arrivals.add(arrivalTime);
    this.value = this.arrivals.value(arrivalTime);
    if (recordHistory)
      this.history.push({ timestamp: arrivalTime, value: this.value });
  }
}

function hashId(id: string): number {
  let value = 2166136261;
  for (let i = 0; i < id.length; i++)
    value = Math.imul(value ^ id.charCodeAt(i), 16777619);
  return value >>> 0;
}

function normalizedRate(rate: number): number {
  return Number.isFinite(rate) ? Math.max(0, Math.min(10, rate)) : 0;
}

function simulatedValue(node: SpatialNode, timestamp: number): number {
  const phase = hashId(node.id) % 1000;
  const wave =
    Math.sin(timestamp / 18_000 + phase) +
    0.32 * Math.sin(timestamp / 3_700 + phase / 3);
  const metric = `${node.metric} ${node.unit}`.toLowerCase();
  if (
    metric.includes("co₂") ||
    metric.includes("co2") ||
    metric.includes("ppm")
  )
    return 650 + 95 * wave;
  if (metric.includes("humidity") || metric.includes("%")) return 48 + 6 * wave;
  if (metric.includes("voltage") || node.unit === "V") return 230 + 2.5 * wave;
  if (metric.includes("power") || node.unit === "kW") return 3.8 + 0.8 * wave;
  if (metric.includes("pressure") || node.unit === "bar")
    return 2.4 + 0.13 * wave;
  if (metric.includes("speed") || node.unit === "km/h")
    return Math.max(0, 22 + 13 * wave);
  if (metric.includes("temperature") || metric.includes("°c"))
    return 21.5 + 1.5 * wave;
  return 40 + 8 * wave;
}

type SimulatedSource = {
  node: SpatialNode;
  record: TelemetryRecord;
  nextArrival: number;
  sequence: number;
};

/** Explicitly simulated telemetry. Counts and pulses reflect arrivals during this session. */
export class DemoTelemetry implements SpatialTelemetry {
  private readonly records = new Map<string, TelemetryRecord>();
  private readonly listeners = new Set<(message: TelemetryMessage) => void>();
  private readonly rateOverrides = new Map<string, number>();
  private readonly brokerLastSample = new Map<string, number>();
  private sources: SimulatedSource[] = [];
  private timer: ReturnType<typeof setInterval> | undefined;
  private started = false;
  private paused = false;
  private disposed = false;

  constructor(nodes: SpatialNode[]) {
    this.setNodes(nodes);
  }

  getSnapshot(id: string): NodeTelemetry | undefined {
    return this.records.get(id);
  }

  subscribe(listener: (message: TelemetryMessage) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  setNodes(nodes: SpatialNode[]): void {
    if (this.disposed) return;
    const now = Date.now();
    const previous = new Map(
      this.sources.map((source) => [source.node.id, source]),
    );
    const surviving = new Set(nodes.map((node) => node.id));
    for (const id of this.records.keys())
      if (!surviving.has(id)) this.records.delete(id);
    for (const id of this.rateOverrides.keys())
      if (!surviving.has(id)) this.rateOverrides.delete(id);
    for (const id of this.brokerLastSample.keys())
      if (!surviving.has(id)) this.brokerLastSample.delete(id);
    this.sources = [];
    for (const node of nodes) {
      if (node.kind === "group") continue;
      const existing = previous.get(node.id);
      if (existing) {
        existing.node = node;
        this.sources.push(existing);
        continue;
      }
      let record = this.records.get(node.id);
      if (!record) {
        record = new TelemetryRecord();
        this.records.set(node.id, record);
      }
      if (node.kind === "broker") continue;
      const rate = normalizedRate(node.baseRate);
      // This history is synthetic, and does not increment observed message counts.
      if (rate > 0)
        for (let i = 119; i >= 0; i--) {
          const timestamp = now - (i * 1_000) / rate;
          record.seed({ timestamp, value: simulatedValue(node, timestamp) });
        }
      this.sources.push({
        node,
        record,
        nextArrival: now + (hashId(node.id) % 1000) / Math.max(0.1, rate),
        sequence: 0,
      });
    }
  }

  setRate(nodeId: string, rate: number): void {
    if (this.disposed) return;
    const source = this.sources.find(({ node }) => node.id === nodeId);
    if (!source) return;
    const clamped = normalizedRate(rate);
    this.rateOverrides.set(nodeId, clamped);
    source.nextArrival = clamped ? Date.now() + 1_000 / clamped : Infinity;
  }

  start(): void {
    if (this.started && !this.disposed) return;
    this.disposed = false;
    this.started = true;
    document.addEventListener("visibilitychange", this.updateRunning);
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
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
    document.removeEventListener("visibilitychange", this.updateRunning);
    this.listeners.clear();
    // Retain bounded state so React StrictMode can start/clean up/start this engine.
    // Once the owner releases the engine, these records are garbage-collected.
  }

  private rateFor(source: SimulatedSource): number {
    return (
      this.rateOverrides.get(source.node.id) ??
      normalizedRate(source.node.baseRate)
    );
  }

  private updateRunning = (): void => {
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
    if (!this.started || this.disposed || this.paused || document.hidden)
      return;
    const now = Date.now();
    for (const source of this.sources) {
      const rate = this.rateFor(source);
      source.nextArrival = rate ? now + 1_000 / rate : Infinity;
    }
    this.timer = setInterval(this.tick, 100);
  };

  private tick = (): void => {
    if (this.disposed || this.paused || document.hidden) return;
    const now = Date.now();
    for (const source of this.sources) {
      const rate = this.rateFor(source);
      if (rate === 0) continue;
      let batchCount = 0;
      while (source.nextArrival <= now && batchCount++ < 4) {
        const sample = {
          timestamp: now,
          value: simulatedValue(source.node, now),
        };
        source.record.receive(sample, now);
        if (source.node.brokerId) {
          const broker = this.records.get(source.node.brokerId);
          const lastHistory =
            this.brokerLastSample.get(source.node.brokerId) ?? 0;
          if (broker) {
            broker.receiveAggregate(now, now - lastHistory >= 1_000);
            if (now - lastHistory >= 1_000)
              this.brokerLastSample.set(source.node.brokerId, now);
          }
        }
        const event: TelemetryMessage = { ...sample, nodeId: source.node.id };
        for (const listener of this.listeners) listener(event);
        source.sequence++;
        const jitter =
          1 + 0.12 * Math.sin(source.sequence + hashId(source.node.id));
        source.nextArrival += (1_000 * jitter) / rate;
      }
      // A stalled tab cannot replay an unbounded backlog as a burst.
      if (source.nextArrival <= now) source.nextArrival = now + 1_000 / rate;
    }
  };
}
