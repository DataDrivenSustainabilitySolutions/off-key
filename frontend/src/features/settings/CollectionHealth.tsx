import { useCallback, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { usePollingLoop } from "@/hooks/use-polling";
import { apiUtils } from "@/lib/api-client";
import { collectionDiagnosis, diagnosticsFresh } from "@/lib/collection-diagnostics";
import { getErrorMessage } from "@/lib/errors";
import { formatExactDateTime, formatRelativeTime } from "@/lib/format-time";
import type { CollectionStatus } from "@/types/collection";

const date = (value: string | null, now: number) =>
  value ? formatRelativeTime(value, now) : "None since worker start";
const problems = new Set([
  "Worker not reporting", "Disconnected", "Collection error", "Broker controller not reporting",
  "Broker routes failed", "Broker disconnected", "Overloaded", "Invalid payloads",
]);
const idle = new Set(["Not configured", "Paused", "Ingress disabled"]);
/** Diagnoses share the dot-and-label indicator used by services and brokers. */
const tone = (title: string) => title === "Collecting" ? "positive"
  : problems.has(title) ? "danger" : idle.has(title) ? "neutral" : "warning";
const rate = (value: number | null) =>
  value === null ? "Measuring…" : `${value.toLocaleString()} /s`;
const queueUsage = (size: number, capacity: number) =>
  `${size.toLocaleString()} / ${capacity.toLocaleString()} (${Math.round(100 * size / capacity)}%)`;

export function CollectionHealth() {
  const [snapshot, setSnapshot] = useState<CollectionStatus | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now);
  // Expire old reports even while a status request is still pending.
  const advanceClock = useCallback(() => setNow(Date.now()), []);
  const refresh = useCallback(async (signal: AbortSignal) => {
    try {
      const result = await apiUtils.get<CollectionStatus>("/v1/system/health");
      if (!signal.aborted) {
        setSnapshot(result);
        setError("");
      }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, []);
  usePollingLoop(refresh, { intervalMs: 3000, overlap: "skip", startImmediately: true, onTick: advanceClock });

  return (
    <SettingsGroup
      title="Collection diagnostics"
      help="Live status for the saved data source configuration. Refreshes automatically every three seconds."
      padded={!snapshot}
    >
      {error && (
        <p role="alert" className="app-settings-group-note text-destructive">
          Collection status unavailable: {error}. Retrying automatically.
        </p>
      )}
      {snapshot ? (
        <CollectionMeasurements snapshot={snapshot} now={now} />
      ) : !error && (
        <p role="status" className="text-muted-foreground">Loading collection status…</p>
      )}
    </SettingsGroup>
  );
}

function CollectionMeasurements({ snapshot, now }: { snapshot: CollectionStatus; now: number }) {
  const [title, explanation] = collectionDiagnosis(snapshot, now);
  const data = snapshot.collection.diagnostics;
  const current = diagnosticsFresh(snapshot.collection, now) &&
    snapshot.collection.revision === snapshot.revision;
  const measurements = data ? [
    ["Incoming to application", rate(data.rates.received)],
    ["Accepted after sampling", rate(data.rates.accepted)],
    ["Numeric rows written", rate(data.rates.written)],
    ["Original-rate queue", queueUsage(data.original_queue, data.original_capacity)],
    ["Database queue", queueUsage(data.database_queue, data.database_capacity)],
    ["Pending latest samples", data.sample_slots.toLocaleString()],
    ["Last incoming message", date(data.last_received_at, now), data.last_received_at],
    ["Last telemetry/state commit", date(data.last_database_write_at, now), data.last_database_write_at],
  ] : [];

  return (
    <>
      <SettingsRow label={<span className={`mn-state mn-state--${tone(title)} is-headline`} role="status">{title}</span>} detail={explanation} />
      {data && !current && (
        <p className="app-settings-group-note">Measurements below are from the last worker report.</p>
      )}
      {data && (
        <dl className="app-settings-list">
          {measurements.map(([label, value, time]) => (
            <div key={label} className="app-settings-row">
              <dt className="app-settings-row-copy app-settings-row-label">{label}</dt>
              <dd className="app-settings-row-trailing tabular-nums" title={time ? formatExactDateTime(time) : undefined}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="app-settings-group-note">
        {data && (
          <p>
            Rates cover the last {data.window_seconds.toLocaleString()} seconds.
            Incoming counts selected MQTT subscriptions, not all upstream broker
            traffic. Accepted includes state and retained snapshots; snapshots
            do not add numeric history. Latest samples normally fill their slots
            while waiting for the next interval.
          </p>
        )}
        <p>
          Since worker start: {(snapshot.collection.records_written ?? 0).toLocaleString()} numeric
          rows written · {(snapshot.collection.counters?.overload_dropped ?? 0).toLocaleString()}{" "}
          observations dropped at queue capacity ·{" "}
          {(snapshot.collection.counters?.invalid ?? 0).toLocaleString()} invalid observations rejected.
        </p>
      </div>
    </>
  );
}
