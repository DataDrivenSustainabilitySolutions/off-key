import { useEffect, useState } from "react";
import { SectionPanel } from "@/components/DashboardLayout";
import { apiUtils } from "@/lib/api-client";
import { collectionDiagnosis, diagnosticsFresh } from "@/lib/collection-diagnostics";
import { getErrorMessage } from "@/lib/errors";
import type { CollectionStatus } from "@/types/collection";

const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "None since worker start";
const rate = (value: number | null) =>
  value === null ? "Measuring…" : `${value.toLocaleString()} /s`;
const queueUsage = (size: number, capacity: number) =>
  `${size.toLocaleString()} / ${capacity.toLocaleString()} (${Math.round(100 * size / capacity)}%)`;

export function CollectionHealth() {
  const [snapshot, setSnapshot] = useState<CollectionStatus | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    let active = true;
    let pending = false;
    const refresh = async () => {
      // Expire old reports even while a status request is still pending.
      setNow(Date.now());
      if (pending) return;
      pending = true;
      try {
        const result = await apiUtils.get<CollectionStatus>("/v1/sources/status");
        if (active) {
          setSnapshot(result);
          setError("");
        }
      } catch (reason) {
        if (active) setError(getErrorMessage(reason));
      } finally {
        pending = false;
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <SectionPanel
      title="Collection diagnostics"
      help="Live status for the saved data source configuration."
    >
      {error && (
        <p role="alert" className="mb-3 text-sm text-destructive">
          Collection status unavailable: {error}. Retrying automatically.
        </p>
      )}
      {snapshot ? (
        <CollectionMeasurements snapshot={snapshot} now={now} />
      ) : !error && (
        <p role="status">Loading collection status…</p>
      )}
    </SectionPanel>
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
    ["Last incoming message", date(data.last_received_at)],
    ["Last telemetry/state commit", date(data.last_database_write_at)],
  ] : [];

  return (
    <>
      <p className="font-medium" role="status">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{explanation}</p>
      {data && (
        <>
          {!current && (
            <p className="mt-3 text-sm">
              Measurements below are from the last worker report.
            </p>
          )}
          <dl className="mt-4 grid gap-4 sm:grid-cols-3">
            {measurements.map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-1 break-words text-sm font-medium">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">
            Rates cover the last {data.window_seconds.toLocaleString()} seconds.
            Incoming counts selected MQTT subscriptions, not all upstream broker
            traffic. Accepted includes state and retained snapshots; snapshots
            do not add numeric history. Latest samples normally fill their slots
            while waiting for the next interval.
          </p>
        </>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Since worker start: {snapshot.collection.records_written ?? 0} numeric
        rows written · {snapshot.collection.counters?.overload_dropped ?? 0}{" "}
        observations dropped at queue capacity ·{" "}
        {snapshot.collection.counters?.invalid ?? 0} invalid observations rejected.
      </p>
    </>
  );
}
