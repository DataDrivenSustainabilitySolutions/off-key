import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatAnomalySensorSet } from "@/lib/anomaly-utils";
import {
  formatAnomalyValue,
  getAnomalyValueLabel,
} from "@/lib/anomaly-semantics";
import { cn } from "@/lib/utils";
import type { Anomaly } from "@/types/charger";
import {
  getOperationalStageDisplay,
  getServiceDeleteActionDisplay,
  getStatusDisplay,
} from "@/types/monitoring";
import type { ActiveService } from "@/types/monitoring";
import { RefreshCw, Trash2 } from "lucide-react";

import { humanize } from "./config";

interface MonitoringDataPanelsProps {
  services: ActiveService[];
  anomalies: Anomaly[];
  loadingServices: boolean;
  loadingAnomalies: boolean;
  onRefreshServices: () => void;
  onRefreshAnomalies: () => void;
  onDeleteService: (service: ActiveService) => void;
}

export function MonitoringDataPanels({
  services,
  anomalies,
  loadingServices,
  loadingAnomalies,
  onRefreshServices,
  onRefreshAnomalies,
  onDeleteService,
}: MonitoringDataPanelsProps) {
  return (
    <>
      <SectionPanel
        title="Active services"
        description="Runtime lifecycle and current stream ownership."
        actions={
          <Button
            variant="outline"
            onClick={onRefreshServices}
            disabled={loadingServices}
          >
            <RefreshCw
              className={cn("h-4 w-4", loadingServices && "animate-spin")}
            />
            Refresh
          </Button>
        }
        contentClassName="p-0"
      >
        {!services.length ? (
          <p className="m-5 rounded-xl border border-dashed p-5 text-sm text-muted-foreground sm:m-6">
            No active monitoring services.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 hover:bg-muted/30">
                  <TableHead>Service</TableHead>
                  <TableHead>Lifecycle</TableHead>
                  <TableHead>Runtime</TableHead>
                  <TableHead>Topics</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {services.map((service) => {
                  const stage = service.operational_status
                    ? getOperationalStageDisplay(service.operational_status)
                    : undefined;
                  const runtime = getStatusDisplay(
                    service.docker_status,
                    service.status,
                  );
                  return (
                    <TableRow key={service.id}>
                      <TableCell>
                        <div className="font-medium">{service.container_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {service.model_type
                            ? humanize(service.model_type)
                            : "Static baseline"}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span
                          className={cn(
                            "rounded-full px-2 py-1 text-xs font-medium",
                            stage?.className ??
                              "bg-muted text-muted-foreground",
                          )}
                        >
                          {stage?.label ?? "Starting"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span
                          className={cn(
                            "rounded-full px-2 py-1 text-xs font-medium",
                            runtime.className,
                          )}
                        >
                          {runtime.label}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-xs">
                        <div className="truncate text-xs text-muted-foreground">
                          {(service.mqtt_topics ?? []).join(", ")}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={
                            getServiceDeleteActionDisplay(service).ariaLabel
                          }
                          onClick={() => onDeleteService(service)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionPanel>

      <SectionPanel
        title="Recent alarm transitions"
        description="Only new threshold crossings are anomaly events; the full evidence path is persisted for charts."
        actions={
          <Button
            variant="outline"
            onClick={onRefreshAnomalies}
            disabled={loadingAnomalies}
          >
            <RefreshCw
              className={cn("h-4 w-4", loadingAnomalies && "animate-spin")}
            />
            Refresh
          </Button>
        }
        contentClassName="p-0"
      >
        {!anomalies.length ? (
          <p className="m-5 rounded-xl border border-dashed p-5 text-sm text-muted-foreground sm:m-6">
            No recent alarm transitions.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 hover:bg-muted/30">
                  <TableHead>Time</TableHead>
                  <TableHead>Sensors</TableHead>
                  <TableHead>Evidence input</TableHead>
                  <TableHead>Type</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {anomalies.slice(0, 50).map((anomaly) => (
                  <TableRow
                    key={
                      anomaly.anomaly_id ??
                      `${anomaly.timestamp}-${anomaly.telemetry_type}`
                    }
                  >
                    <TableCell>
                      {new Date(anomaly.timestamp).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      {formatAnomalySensorSet(anomaly.sensor_set) ||
                        anomaly.telemetry_type}
                    </TableCell>
                    <TableCell>
                      <div className="font-mono text-xs">
                        {formatAnomalyValue(
                          anomaly.anomaly_value,
                          anomaly.value_type,
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {getAnomalyValueLabel(anomaly.value_type)}
                      </div>
                    </TableCell>
                    <TableCell className="capitalize">
                      {anomaly.anomaly_type.replace(/_/g, " ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionPanel>
    </>
  );
}
