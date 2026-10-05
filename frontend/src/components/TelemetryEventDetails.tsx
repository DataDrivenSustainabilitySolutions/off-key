import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatAnomalySensorSet, MULTIVARIATE_TELEMETRY_TYPE } from "@/lib/anomaly-utils";
import { formatAnomalyValue, getAnomalyValueLabel } from "@/lib/anomaly-semantics";
import { formatNumber } from "@/lib/telemetry-chart";
import { formatTelemetryEventTime, type TelemetryEventGroup } from "@/lib/telemetry-events";

interface Props {
  groups: TelemetryEventGroup[];
  timeZone: string;
  unit?: string;
}

export function TelemetryEventDetails({ groups, timeZone, unit }: Props) {
  const events = groups.flatMap((group) => group.events);
  if (events.length === 0) return null;
  return (
    <details className="mt-3 min-w-0 rounded-md border border-border text-xs">
      <summary className="cursor-pointer rounded-md px-3 py-2 font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
        Event details ({events.length})
      </summary>
      <Table aria-label="Anomaly event details" className="text-xs">
        <TableHeader>
          <TableRow>
            {["Event time", "Event ID", "Type", "Event value", "Sensors", "Telemetry sample time", "Value", "Offset"].map((heading) => (
              <TableHead key={heading} scope="col">{heading}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((event) => (
            <TableRow key={event.anomaly.anomaly_id}>
              <TableCell>{formatTelemetryEventTime(event.time, timeZone)}</TableCell>
              <TableCell>{event.anomaly.anomaly_id}</TableCell>
              <TableCell>{event.anomaly.anomaly_type.replace(/_/gu, " ")}</TableCell>
              <TableCell>{getAnomalyValueLabel(event.anomaly.value_type)}: {formatAnomalyValue(event.anomaly.anomaly_value, event.anomaly.value_type)}</TableCell>
              <TableCell>{formatAnomalySensorSet(event.anomaly.sensor_set)}</TableCell>
              <TableCell>{event.sample ? <>
                {formatTelemetryEventTime(event.sample.time, timeZone)}
                {event.anomaly.telemetry_type === MULTIVARIATE_TELEMETRY_TYPE || (event.anomaly.sensor_set?.length ?? 0) > 1 ? " (context)" : ""}
              </> : "No nearby telemetry sample"}</TableCell>
              <TableCell>{event.sample ? `${formatNumber(event.sample.value)}${unit ? ` ${unit}` : ""}` : "—"}</TableCell>
              <TableCell>{event.sample ? `${event.sample.time - event.time >= 0 ? "+" : ""}${event.sample.time - event.time} ms` : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </details>
  );
}
