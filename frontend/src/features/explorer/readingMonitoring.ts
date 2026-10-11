import type { TelemetryDataPoint } from "@/types/charger";
import type { Catalog } from "@/types/collection";
import type { SystemConnection, SystemStream } from "../spatial/systemTypes";

export type ReadingMonitoringBinding = { entityId: string; telemetryType: string };

/** Bridge existing collection identities by their exact input, never by a display name. */
export function resolveReadingMonitoringBinding(
  connection: Pick<SystemConnection, "host" | "port" | "transport" | "tls">,
  stream: Pick<SystemStream, "topic" | "payload_pointer" | "value_type">,
  catalog: Catalog,
): ReadingMonitoringBinding | undefined {
  if (connection.transport !== "tcp" || connection.tls || stream.payload_pointer) return;
  const hostname = (host: string) => host.toLowerCase().replace(/\.$/, "");
  const matches = new Map<string, ReadingMonitoringBinding>();
  for (const source of catalog.sources) {
    if (hostname(source.host) !== hostname(connection.host) || source.port !== connection.port) continue;
    for (const entity of source.chargers) {
      for (const sensor of entity.sensors) {
        if (sensor.upstream_topic !== stream.topic || sensor.value_type !== stream.value_type) continue;
        const binding = { entityId: entity.id, telemetryType: sensor.key };
        matches.set(JSON.stringify(binding), binding);
      }
    }
  }
  // An ambiguous input must not display another entity's monitoring results.
  return matches.size === 1 ? matches.values().next().value : undefined;
}

export function mergeReadingHistory(
  current: readonly TelemetryDataPoint[],
  incoming: readonly TelemetryDataPoint[],
  limit = 4096,
): TelemetryDataPoint[] {
  const points = new Map<number, TelemetryDataPoint>();
  for (const point of [...current, ...incoming]) {
    const time = Date.parse(point.timestamp);
    if (Number.isFinite(time) && Number.isFinite(point.value)) points.set(time, point);
  }
  return [...points.entries()].sort(([left], [right]) => left - right)
    .slice(-limit).map(([, point]) => point);
}
