import { ApiRequestError, apiUtils } from "@/lib/api-client";
import type { SystemDocument } from "./systemTypes";
import type { Sample, LiveTelemetryStore, TelemetryMessage } from "./systemLiveTypes";
import type {
  LiveBatch,
  LiveConnection,
  LiveLease,
  LiveNodeSnapshot,
  LiveSample,
  LiveStatus,
  LiveStream,
} from "./systemLiveTypes";

export const SYSTEM_LIVE_ENDPOINT = "/v1/system/live";
export const LIVE_HISTORY_LIMIT = 8192;
const HISTORY_MS = 2 * 60 * 60 * 1000;
const POLL_MS = 1000;
const RENEW_MS = 15000;
const SERVICE_TIMEOUT_MS = 20000;
const MAX_PULSES = 60;
type TimeoutKind = "brokers" | "read" | "renew";

type Transport = {
  create: (revision: number, streamIds?: string[]) => Promise<LiveLease>;
  renew: (leaseId: string, signal: AbortSignal, streamIds?: string[]) => Promise<LiveLease>;
  read: (sequence: number, signal: AbortSignal) => Promise<LiveBatch>;
  release: (leaseId: string) => Promise<unknown>;
};
const options = { redirectOnUnauthorized: false, timeout: 10000 };
const transport: Transport = {
  create: (revision, streamIds) =>
    apiUtils.post(
      `${SYSTEM_LIVE_ENDPOINT}/leases`,
      { expected_revision: revision, stream_ids: streamIds },
      options,
    ),
  renew: (id, signal, streamIds) =>
    apiUtils.put<LiveLease>(
      `${SYSTEM_LIVE_ENDPOINT}/leases/${encodeURIComponent(id)}`,
      { stream_ids: streamIds },
      { ...options, signal },
    ),
  read: (sequence, signal) =>
    apiUtils.get(SYSTEM_LIVE_ENDPOINT, {
      ...options,
      signal,
      params: { after_sequence: sequence },
    }),
  release: (id) =>
    apiUtils.delete(
      `${SYSTEM_LIVE_ENDPOINT}/leases/${encodeURIComponent(id)}`,
      undefined,
      options,
    ),
};
const timestamp = (value: string | null): number | null => {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
};
const numeric = (value: LiveSample["value"]): number | undefined =>
  typeof value === "boolean"
    ? Number(value)
    : typeof value === "number" && Number.isFinite(value)
      ? value
      : undefined;
const emptyStatus = (): LiveStatus => ({
  phase: "idle",
  message: "Disconnected. Connect to receive live data.",
  observing: false,
  active: false,
  connections: [],
});

/** Fixed global history. A large system cannot allocate an unbounded buffer per stream. */
class LiveHistory {
  private rows: Array<LiveSample | undefined> = new Array(LIVE_HISTORY_LIMIT);
  private cursor = 0;
  private size = 0;
  private version = 0;
  private cached = new Map<
    string,
    { version: number; samples: readonly Sample[] }
  >();
  private latestSequences = new Map<string, number>();
  private slots = new Map<string, number>();

  clear() {
    this.rows = new Array(LIVE_HISTORY_LIMIT);
    this.cursor = this.size = 0;
    this.version++;
    this.cached.clear();
    this.latestSequences.clear();
    this.slots.clear();
  }

  resetCursor() { this.latestSequences.clear(); }

  add(sample: LiveSample) {
    const time = timestamp(sample.received_at);
    if (
      numeric(sample.value) === undefined ||
      time === null ||
      sample.sequence <= (this.latestSequences.get(sample.stream_id) ?? -1)
    )
      return;
    this.latestSequences.set(sample.stream_id, sample.sequence);
    const second = Math.floor(time / 1000);
    const key = `${sample.stream_id}\u0000${second}`;
    const prior = this.slots.get(key);
    if (prior !== undefined) {
      // A scope reset replays observations. Keep the newest real arrival in
      // each second, including when the server's sequence counter restarted.
      if (time < timestamp(this.rows[prior]!.received_at)!) return;
      this.rows[prior] = sample;
      this.version++;
      return;
    }
    const evicted = this.rows[this.cursor];
    if (evicted) this.slots.delete(`${evicted.stream_id}\u0000${Math.floor(timestamp(evicted.received_at)! / 1000)}`);
    this.slots.set(key, this.cursor);
    this.rows[this.cursor] = sample;
    this.cursor = (this.cursor + 1) % LIVE_HISTORY_LIMIT;
    this.size = Math.min(LIVE_HISTORY_LIMIT, this.size + 1);
    this.version++;
  }

  samples(id: string): readonly Sample[] {
    const previous = this.cached.get(id);
    if (previous?.version === this.version) return previous.samples;
    const result: Sample[] = [];
    const start =
      (this.cursor - this.size + LIVE_HISTORY_LIMIT) % LIVE_HISTORY_LIMIT;
    const cutoff = Date.now() - HISTORY_MS;
    for (let index = 0; index < this.size; index++) {
      const sample = this.rows[(start + index) % LIVE_HISTORY_LIMIT];
      if (sample?.stream_id !== id) continue;
      const time = timestamp(sample.received_at);
      const value = numeric(sample.value);
      if (time !== null && time >= cutoff && value !== undefined)
        result.push({ timestamp: time, value });
    }
    // Only the inspected stream needs a materialized history array.
    this.cached.clear();
    result.sort((left, right) => left.timestamp - right.timestamp);
    this.cached.set(id, { version: this.version, samples: result });
    return result;
  }
}

/** Authenticated, leased MQTT preview. Counts come from receipts, never render ticks. */
export class SystemLiveTelemetry implements LiveTelemetryStore {
  private document: SystemDocument | undefined;
  private revision = 0;
  private owner = "";
  private canStart = false;
  private sequence = 0;
  private hasBaseline = false;
  private generation = 0;
  private requested = false;
  private leaseId: string | undefined;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;
  private renewTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly timeouts = new Map<
    TimeoutKind,
    ReturnType<typeof setTimeout>
  >();
  private controller: AbortController | undefined;
  private renewController: AbortController | undefined;
  private readonly records = new Map<string, LiveStream>();
  private readonly connections = new Map<string, LiveConnection>();
  private readonly history = new LiveHistory();
  private readonly snapshots = new Map<string, LiveNodeSnapshot | undefined>();
  private streamIds = new Set<string>();
  private connectionIds = new Set<string>();
  private deviceStreams = new Map<string, string[]>();
  private readonly pulses = new Set<(message: TelemetryMessage) => void>();
  private readonly updates = new Set<() => void>();
  private status: LiveStatus = emptyStatus();
  private priorityId: string | null = null;
  private scopeIds: string[] | undefined;
  private scopeVersion = 0;
  private renewing = false;
  private pulseOffset = 0;

  constructor(private readonly api: Transport = transport) {}

  configure(
    document: SystemDocument,
    revision: number,
    owner: string,
    canStart: boolean,
  ) {
    if (
      this.owner !== owner ||
      this.revision !== revision ||
      this.document === undefined ||
      (this.canStart !== canStart && this.requested)
    ) {
      this.stop();
      this.revision = revision;
      this.owner = owner;
    }
    if (this.document !== document) {
      this.streamIds = new Set(document.streams.map((stream) => stream.id));
      this.connectionIds = new Set(
        document.connections.map((connection) => connection.id),
      );
      this.deviceStreams = new Map(
        document.devices.map((device) => [device.id, []]),
      );
      for (const stream of document.streams) {
        if (stream.device_id)
          this.deviceStreams.get(stream.device_id)?.push(stream.id);
      }
      this.snapshots.clear();
    }
    this.document = document;
    this.canStart = canStart;
  }

  getStatus = (): LiveStatus => this.status;
  subscribeUpdates = (listener: () => void): (() => void) => {
    this.updates.add(listener);
    return () => this.updates.delete(listener);
  };
  subscribe(listener: (message: TelemetryMessage) => void): () => void {
    this.pulses.add(listener);
    return () => this.pulses.delete(listener);
  }
  setPriority(id: string | null) {
    this.priorityId = id;
  }
  setScope(ids: readonly string[]) {
    const next = [...new Set(ids)].filter((id) => this.streamIds.has(id)).sort();
    if (JSON.stringify(next) === JSON.stringify(this.scopeIds)) return;
    this.scopeIds = next;
    this.scopeVersion++;
    if (this.leaseId) this.scheduleRenew(this.generation, 150);
  }
  private publish(status?: LiveStatus) {
    if (status) this.status = status;
    for (const listener of this.updates) listener();
  }
  private clear() {
    this.sequence = 0;
    this.hasBaseline = false;
    this.records.clear();
    this.connections.clear();
    this.history.clear();
    this.snapshots.clear();
  }
  private resetCursor() {
    this.sequence = 0;
    this.hasBaseline = false;
    this.connections.clear();
    this.history.resetCursor();
    this.snapshots.clear();
  }
  private cancel() {
    this.generation++;
    clearTimeout(this.pollTimer);
    clearTimeout(this.renewTimer);
    for (const timer of this.timeouts.values()) clearTimeout(timer);
    this.timeouts.clear();
    this.controller?.abort();
    this.renewController?.abort();
    const lease = this.leaseId;
    this.leaseId = undefined;
    if (lease) void this.api.release(lease).catch(() => {});
  }
  stop() {
    this.requested = false;
    this.cancel();
    this.clear();
    this.publish(emptyStatus());
  }
  pause() {
    if (!this.requested) return;
    this.cancel();
    this.resetCursor();
    this.publish({
      ...this.status,
      active: false,
      connections: [],
      phase: "paused",
      message: "Live connection paused while this tab is hidden.",
    });
  }
  resume() {
    if (this.requested && this.status.phase === "paused") void this.start();
  }
  async start() {
    if (!this.document || !this.owner) return;
    this.cancel();
    this.resetCursor();
    this.requested = true;
    const context = this.generation;
    this.publish({
      phase: "connecting",
      message: this.canStart
        ? "Connecting to your configured brokers…"
        : "Opening the active live connection…",
      observing: !this.canStart,
      active: true,
      connections: [],
    });
    this.watchTimeout(
      "read",
      "The live service could not be reached. Check your connection, then retry.",
    );
    if (this.canStart) {
      try {
        // Let creation finish so a late response can release its lease after a navigation.
        const scopeVersion = this.scopeVersion;
        const lease = await this.api.create(this.revision, this.scopeIds);
        if (context !== this.generation) {
          void this.api.release(lease.lease_id).catch(() => {});
          return;
        }
        this.clearTimeout("read");
        this.leaseId = lease.lease_id;
        this.accept(lease.telemetry, false);
        if (context === this.generation) this.scheduleRenew(context, scopeVersion === this.scopeVersion ? RENEW_MS : 150);
      } catch (error) {
        if (context !== this.generation) return;
        this.fail(error);
        return;
      }
    }
    if (context === this.generation) void this.poll(context);
  }

  private fail(error: unknown) {
    this.requested = false;
    this.cancel();
    this.clear();
    const message =
      error instanceof Error
        ? error.message
        : "The live connection could not be opened.";
    this.publish({ ...emptyStatus(), phase: "error", message });
  }
  private unavailable(
    message: string,
    phase: "error" | "blocked" = "error",
    connections = this.status.connections,
  ) {
    this.requested = false;
    this.cancel();
    // Keep the last readings and broker diagnostics available for inspection.
    this.publish({ ...this.status, active: false, phase, message, connections });
  }
  private watchTimeout(
    kind: TimeoutKind,
    message: string,
    delay = SERVICE_TIMEOUT_MS,
  ) {
    if (this.timeouts.has(kind)) return;
    this.timeouts.set(
      kind,
      setTimeout(() => this.unavailable(message), delay),
    );
  }
  private clearTimeout(kind: TimeoutKind) {
    clearTimeout(this.timeouts.get(kind));
    this.timeouts.delete(kind);
  }
  private scheduleRenew(context: number, delay: number) {
    clearTimeout(this.renewTimer);
    this.renewTimer = setTimeout(() => void this.renew(context), delay);
  }
  private async renew(context: number) {
    const id = this.leaseId;
    if (context !== this.generation || !id || this.renewing) return;
    this.renewing = true;
    const scopeVersion = this.scopeVersion;
    const controller = new AbortController();
    this.renewController = controller;
    this.watchTimeout(
      "renew",
      "The live session could not be renewed. Check your connection, then retry.",
    );
    try {
      const lease = await this.api.renew(id, controller.signal, this.scopeIds);
      if (context !== this.generation) return;
      this.clearTimeout("renew");
      if (lease.telemetry.revision !== this.revision) {
        this.fail(
          new Error(
            "The saved system changed. Connect again to use its current definition.",
          ),
        );
        return;
      }
      this.scheduleRenew(context, scopeVersion === this.scopeVersion ? RENEW_MS : 150);
    } catch (error) {
      if (context !== this.generation || controller.signal.aborted) return;
      if (
        error instanceof ApiRequestError &&
        [401, 403, 404, 409].includes(error.status ?? 0)
      )
        this.fail(error);
      else {
        this.publish({
          ...this.status,
          phase: "reconnecting",
          message: "Reconnecting to the local preview service…",
        });
        this.scheduleRenew(context, 2000);
      }
    } finally {
      this.renewing = false;
      if (context === this.generation && this.leaseId && scopeVersion !== this.scopeVersion)
        this.scheduleRenew(context, 150);
    }
  }
  private async poll(context: number) {
    if (context !== this.generation) return;
    const controller = new AbortController();
    this.controller = controller;
    this.watchTimeout(
      "read",
      "The live service could not be reached. Check your connection, then retry.",
    );
    let delay = POLL_MS;
    try {
      const batch = await this.api.read(this.sequence, controller.signal);
      if (context !== this.generation) return;
      this.clearTimeout("read");
      this.accept(batch, true);
    } catch (error) {
      if (context !== this.generation || controller.signal.aborted) return;
      if (
        error instanceof ApiRequestError &&
        [401, 403, 404, 409].includes(error.status ?? 0)
      ) {
        this.fail(error);
        return;
      }
      delay = 3000;
      this.publish({
        ...this.status,
        phase: "reconnecting",
        message: "Reconnecting to the live data service…",
      });
    }
    if (context === this.generation)
      this.pollTimer = setTimeout(() => void this.poll(context), delay);
  }

  /** Apply a coalesced batch once; replay/retained rows never create traffic pulses. */
  accept(batch: LiveBatch, animate: boolean) {
    if (batch.revision !== this.revision) {
      this.fail(
        new Error(
          "The saved system changed. Connect again to use its current definition.",
        ),
      );
      return;
    }
    const previousSequence = this.sequence;
    const replay = !this.hasBaseline || (batch.reset && previousSequence > 0);
    const previousFresh = new Map(
      [...this.records].map(([id, record]) => [id, record.fresh_count]),
    );
    if (batch.reset) this.resetCursor();
    const knownStreams = this.streamIds;
    const knownConnections = this.connectionIds;
    this.snapshots.clear();
    for (const connection of batch.connections)
      if (knownConnections.has(connection.connection_id))
        this.connections.set(connection.connection_id, connection);
    for (const record of batch.streams)
      if (knownStreams.has(record.stream_id))
        this.records.set(record.stream_id, record);
    for (const sample of batch.samples)
      if (knownStreams.has(sample.stream_id)) this.history.add(sample);
    this.sequence = batch.sequence;
    this.hasBaseline = true;
    if (animate && !replay && batch.sequence > previousSequence) {
      const changed = batch.streams.filter(
        (record) =>
          knownStreams.has(record.stream_id) &&
          record.fresh_count > (previousFresh.get(record.stream_id) ?? 0) &&
          timestamp(record.fresh_received_at) !== null &&
          Date.now() - timestamp(record.fresh_received_at)! < 5000,
      );
      // Rotate capped visual representatives. Cumulative counters retain every receipt.
      const ordered = [
        ...changed.filter((record) => record.stream_id === this.priorityId),
        ...changed
          .filter((record) => record.stream_id !== this.priorityId)
          .slice(this.pulseOffset),
        ...changed
          .filter((record) => record.stream_id !== this.priorityId)
          .slice(0, this.pulseOffset),
      ];
      for (const record of ordered.slice(0, MAX_PULSES)) {
        const message = {
          nodeId: record.stream_id,
          timestamp: timestamp(record.fresh_received_at)!,
          value: numeric(record.value ?? "") ?? Number.NaN,
        };
        for (const listener of this.pulses) listener(message);
      }
      this.pulseOffset = changed.length
        ? (this.pulseOffset + MAX_PULSES) % changed.length
        : 0;
    }
    const connections = [...this.connections.values()];
    const connected = connections.some(
      (connection) => connection.state === "connected",
    );
    const reconnecting = connections.some(
      (connection) => connection.state === "reconnecting",
    );
    const connecting = connections.some(
      (connection) => connection.state === "connecting",
    );
    const blocked =
      connections.length > 0 &&
      connections.every((connection) =>
        ["blocked", "error", "stopped"].includes(connection.state),
      );
    if (this.requested) {
      if (batch.mode !== "live" || connected || (this.scopeIds?.length === 0 && !connections.length)) this.clearTimeout("brokers");
      else if (!blocked) {
        this.watchTimeout(
          "brokers",
          "The brokers could not be reached. Check network or VPN access, then retry.",
          ((batch.limits.connect_timeout_seconds ?? 15) + 5) * 1000,
        );
      }
      if (batch.mode === "live" && blocked) {
        this.unavailable(
          connections.find((connection) => connection.message)?.message ??
            "The configured connections could not be opened. Select a broker for details.",
          connections.some((connection) => connection.state === "error")
            ? "error"
            : "blocked",
          connections,
        );
        return;
      }
    }
    const phase =
      batch.mode !== "live"
        ? "waiting"
        : connected
          ? "live"
          : reconnecting
            ? "reconnecting"
            : connecting
              ? "connecting"
              : blocked
                ? "blocked"
                : "waiting";
    this.publish({
      phase,
      dataSource: batch.data_source ?? "broker",
      observing: !this.canStart,
      active: this.requested,
      connections,
      message:
        batch.mode !== "live"
          ? "No live connection is active. An administrator can connect this system."
          : this.scopeIds?.length === 0 && !connections.length
            ? "Select a reading to view live data."
          : connected
            ? batch.data_source === "simulated"
              ? "Simulated data · memory only"
              : "Live data · memory only"
            : blocked
              ? "The configured connections could not be opened. Select a broker for details."
              : "Waiting for broker connection…",
    });
  }

  getSnapshot(id: string): LiveNodeSnapshot | undefined {
    if (this.snapshots.has(id)) return this.snapshots.get(id);
    const snapshot = this.createSnapshot(id);
    this.snapshots.set(id, snapshot);
    return snapshot;
  }

  private createSnapshot(id: string): LiveNodeSnapshot | undefined {
    const history = this.history;
    const record = this.records.get(id);
    if (record)
      return {
        latestValue: record.value,
        value: numeric(record.value ?? "") ?? Number.NaN,
        receivedAt: timestamp(record.received_at),
        lastSeen: timestamp(record.fresh_received_at) ?? 0,
        received: record.fresh_count,
        rate: record.rate_hz,
        get samples() {
          return history.samples(id);
        },
        retained: record.is_retained,
        retainedCount: record.retained_count,
        decodeErrors: record.decode_errors,
        isAggregate: false,
      };
    const connection = this.connections.get(id);
    if (connection)
      return {
        latestValue: null,
        value: connection.rate_hz,
        receivedAt: timestamp(connection.fresh_received_at),
        lastSeen: timestamp(connection.fresh_received_at) ?? 0,
        received: connection.fresh_count,
        rate: connection.rate_hz,
        samples: [],
        retained: false,
        retainedCount: connection.retained_count,
        decodeErrors: 0,
        isAggregate: true,
      };
    const streamIds = this.deviceStreams.get(id);
    if (!streamIds) return undefined;
    const records = streamIds.flatMap(
      (streamId) => this.records.get(streamId) ?? [],
    );
    if (!records.length) return undefined;
    return {
      latestValue: null,
      value: records.reduce((sum, stream) => sum + stream.rate_hz, 0),
      receivedAt:
        Math.max(
          ...records.map((stream) => timestamp(stream.fresh_received_at) ?? 0),
        ) || null,
      lastSeen: Math.max(
        ...records.map((stream) => timestamp(stream.fresh_received_at) ?? 0),
      ),
      received: records.reduce((sum, stream) => sum + stream.fresh_count, 0),
      rate: records.reduce((sum, stream) => sum + stream.rate_hz, 0),
      samples: [],
      retained: false,
      retainedCount: records.reduce(
        (sum, stream) => sum + stream.retained_count,
        0,
      ),
      decodeErrors: records.reduce(
        (sum, stream) => sum + stream.decode_errors,
        0,
      ),
      isAggregate: true,
    };
  }
}
