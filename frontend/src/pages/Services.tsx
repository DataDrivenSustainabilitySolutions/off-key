import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getStatusDisplay } from "@/types/monitoring";
import type { ActiveService } from "@/types/monitoring";

const extractChargerIdFromContainer = (containerName: string): string => {
  const match = containerName.match(/^radar-(.+)-\d+$/);
  return match ? match[1] : "Unknown";
};

const getServiceModeLabel = (service: ActiveService): string => {
  if (service.monitoring_strategy === "static_baseline") {
    return "Static";
  }
  if (service.monitoring_strategy === "adaptive_stream") {
    return "Dynamic";
  }
  return "Unknown";
};

const canStopService = (service: ActiveService): boolean => {
  const dockerStatus = service.docker_status?.toLowerCase();
  return !["not_found", "removed", "stopped"].includes(dockerStatus || "");
};

export default function Services() {
  const [services, setServices] = useState<ActiveService[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const loadServices = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await apiUtils.get<ActiveService[]>(
        `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?include_docker_status=true`
      );
      setServices(response || []);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to load services: ${message}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadServices();
    const intervalId = window.setInterval(() => {
      void loadServices();
    }, 15000);

    return () => window.clearInterval(intervalId);
  }, [loadServices]);

  const runningCount = useMemo(
    () =>
      services.filter((service) => service.docker_status?.toLowerCase() === "running")
        .length,
    [services]
  );
  const missingCount = useMemo(
    () =>
      services.filter((service) => service.docker_status?.toLowerCase() === "not_found")
        .length,
    [services]
  );
  const staticCount = useMemo(
    () =>
      services.filter((service) => service.monitoring_strategy === "static_baseline")
        .length,
    [services]
  );

  const stopService = useCallback(
    async (containerName: string) => {
      if (!confirm(`Stop and remove monitoring service "${containerName}"?`)) {
        return;
      }

      try {
        await apiUtils.delete(
          `${API_CONFIG.ENDPOINTS.MONITORING.STOP}?container_name=${encodeURIComponent(
            containerName
          )}`
        );
        toast.success(`Service "${containerName}" stopped`);
        await loadServices();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`Failed to stop service: ${message}`);
      }
    },
    [loadServices]
  );

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Monitoring"
          title="Services"
          description="Inspect RADAR monitoring workloads and their live Docker state."
          actions={
            <Button variant="outline" onClick={loadServices} disabled={isLoading}>
              <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              Refresh
            </Button>
          }
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <MetricCard label="Services" value={services.length} helper="Tracked" />
          <MetricCard
            label="Running"
            value={runningCount}
            helper="Docker state"
            tone={runningCount > 0 ? "success" : "default"}
          />
          <MetricCard
            label="Static"
            value={staticCount}
            helper="Baseline mode"
            tone="info"
          />
          <MetricCard
            label="Missing"
            value={missingCount}
            helper="DB row without workload"
            tone={missingCount > 0 ? "danger" : "default"}
          />
        </div>

        <SectionPanel
          title="Monitoring Services"
          description={
            isLoading ? "Refreshing service state..." : `${services.length} loaded`
          }
          contentClassName="p-0"
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 hover:bg-muted/40">
                <TableHead>Service</TableHead>
                <TableHead>Charger</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Topics</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && services.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                    Loading services...
                  </TableCell>
                </TableRow>
              ) : services.length > 0 ? (
                services.map((service) => {
                  const status = getStatusDisplay(
                    service.docker_status,
                    service.status
                  );
                  const chargerId = extractChargerIdFromContainer(
                    service.container_name
                  );
                  const isStoppable = canStopService(service);

                  return (
                    <TableRow key={service.id}>
                      <TableCell className="max-w-[16rem] truncate font-medium">
                        {service.container_name}
                      </TableCell>
                      <TableCell>
                        {chargerId === "Unknown" ? (
                          chargerId
                        ) : (
                          <Link
                            to={`/monitoring/${chargerId}`}
                            className="inline-flex items-center gap-1 hover:underline"
                          >
                            {chargerId}
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Link>
                        )}
                      </TableCell>
                      <TableCell>{getServiceModeLabel(service)}</TableCell>
                      <TableCell>{service.model_type || "Unknown"}</TableCell>
                      <TableCell>
                        <div
                          className="max-w-[18rem] truncate"
                          title={service.mqtt_topics.join(", ")}
                        >
                          {service.mqtt_topics.length > 0
                            ? service.mqtt_topics.join(", ")
                            : "None"}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ${status.className}`}
                        >
                          {status.label}
                        </span>
                      </TableCell>
                      <TableCell>
                        {service.created_at
                          ? new Date(service.created_at).toLocaleString()
                          : "Unknown"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          disabled={!isStoppable}
                          onClick={() => stopService(service.container_name)}
                          aria-label={
                            isStoppable
                              ? "stop service"
                              : "service already stopped"
                          }
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                    No monitoring services found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </SectionPanel>
      </PageShell>
    </>
  );
}
