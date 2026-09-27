import { useEffect, useState } from "react";
import { SectionPanel } from "@/components/DashboardLayout";
import { collectionDiagnosis, diagnosticsFresh } from "@/lib/collection-diagnostics";
import type { CatalogSnapshot } from "@/types/collection";

const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "None since worker start";
const rate = (value: number | null) =>
  value === null ? "Measuring…" : `${value.toLocaleString()} /s`;
const queueUsage = (size: number, capacity: number) =>
  `${size.toLocaleString()} / ${capacity.toLocaleString()} (${Math.round(100 * size / capacity)}%)`;

export function CollectionHealth({ snapshot }: { snapshot: CatalogSnapshot }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    // Expire old reports even if the API stops responding and props never change.
    const timer = setInterval(() => setNow(Date.now()), 3000);
    return () => clearInterval(timer);
  }, []);
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
    <SectionPanel
      title="Collection diagnostics"
      description="Status of the saved configuration; unsaved edits do not affect collection."
    >
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
    </SectionPanel>
  );
}
