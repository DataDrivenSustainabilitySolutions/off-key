import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  RadioTower,
  RefreshCw,
  Trash2,
} from "lucide-react";
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
import { cn } from "@/lib/utils";
import {
  getOperationalStageDisplay,
  getServiceDeleteActionDisplay,
  getStatusDisplay,
} from "@/types/monitoring";
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

const getModeBadgeClassName = (service: ActiveService): string => {
  if (service.monitoring_strategy === "static_baseline") {
    return "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/25 dark:text-sky-200";
  }
  if (service.monitoring_strategy === "adaptive_stream") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200";
  }
  return "border-border bg-muted text-muted-foreground";
};

function StatusBadge({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        className
      )}
    >
      {label}
    </span>
  );
}

function ModeBadge({ service }: { service: ActiveService }) {
  const Icon =
    service.monitoring_strategy === "static_baseline" ? Database : Activity;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        getModeBadgeClassName(service)
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {getServiceModeLabel(service)}
    </span>
  );
}

function StageSummary({ service }: { service: ActiveService }) {
  const operational = service.operational_status;
  const stage = getOperationalStageDisplay(operational);
  const progress = operational.progress;
  const percent = progress
    ? Math.min(100, Math.round((progress.current / Math.max(progress.target, 1)) * 100))
    : 0;

  return (
    <div className="min-w-40">
      <StatusBadge label={stage.label} className={stage.className} />
      {progress ? (
        <div className="mt-2 w-36">
          <div className="mb-1 text-xs text-muted-foreground">
            {progress.current}/{progress.target}
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      ) : operational.detail ? (
        <div className="mt-1 max-w-40 text-xs text-muted-foreground">
          {operational.detail}
        </div>
      ) : null}
      {operational.is_stale ? (
        <div className="mt-1 text-xs text-yellow-700 dark:text-yellow-300">
          Stale heartbeat
        </div>
      ) : null}
    </div>
  );
}

function EmptyServicesState() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center px-4 py-10 text-center">
      <div className="mb-3 flex size-10 items-center justify-center rounded-md border bg-muted/30 text-muted-foreground">
        <RadioTower className="h-5 w-5" />
      </div>
      <div className="text-sm font-medium">No monitoring services found</div>
      <div className="mt-1 max-w-md text-sm text-muted-foreground">
        New RADAR workloads will appear here after they are started from a charger
        monitoring page.
      </div>
    </div>
  );
}

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
    const timeoutId = window.setTimeout(() => {
      void loadServices();
    }, 0);
    const intervalId = window.setInterval(() => {
      void loadServices();
    }, 15000);

    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };
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
  const dynamicCount = useMemo(
    () =>
      services.filter((service) => service.monitoring_strategy === "adaptive_stream")
        .length,
    [services]
  );

  const deleteService = useCallback(
    async (service: ActiveService) => {
      const action = getServiceDeleteActionDisplay(service);
      if (!confirm(action.confirmation)) {
        return;
      }

      try {
        await apiUtils.delete(
          API_CONFIG.ENDPOINTS.MONITORING.DELETE(service.id),
          undefined,
          { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT }
        );
        toast.success(action.success);
        await loadServices();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`Failed to delete service: ${message}`);
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
          <MetricCard label="Services" value={services.length} helper="Tracked workloads" />
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

        <div className="flex flex-col gap-3 rounded-md border border-border/80 bg-muted/20 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className={cn(
                "flex size-9 shrink-0 items-center justify-center rounded-md border",
                missingCount > 0
                  ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200"
                  : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200"
              )}
            >
              {missingCount > 0 ? (
                <AlertTriangle className="h-4 w-4" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium">
                {missingCount > 0
                  ? `${missingCount} services need attention`
                  : "Service inventory is clean"}
              </div>
              <div className="text-sm text-muted-foreground">
                {runningCount} running, {staticCount} static, {dynamicCount} dynamic
              </div>
            </div>
          </div>
          <div className="text-xs text-muted-foreground">
            Auto-refreshes every 15 seconds
          </div>
        </div>

        <SectionPanel
          title="Monitoring Services"
          description={
            isLoading ? "Refreshing service state..." : `${services.length} loaded`
          }
          contentClassName="p-0"
        >
          {isLoading && services.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center px-4 py-10 text-center">
              <RefreshCw className="mb-3 h-5 w-5 animate-spin text-muted-foreground" />
              <div className="text-sm font-medium">Loading services</div>
              <div className="mt-1 text-sm text-muted-foreground">
                Fetching current workload state.
              </div>
            </div>
          ) : services.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead>Service</TableHead>
                  <TableHead>Charger</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Topics</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {services.map((service) => {
                    const status = getStatusDisplay(
                      service.docker_status,
                      service.status
                    );
                    const chargerId = extractChargerIdFromContainer(
                      service.container_name
                    );
                    const deleteAction = getServiceDeleteActionDisplay(service);
                    const topicPreview = service.mqtt_topics.slice(0, 2);

                    return (
                      <TableRow key={service.id} className="align-top">
                        <TableCell>
                          <div className="max-w-[18rem] truncate font-medium">
                            {service.container_name}
                          </div>
                          <div className="mt-1 max-w-[18rem] truncate font-mono text-xs text-muted-foreground">
                            {service.container_id || service.id}
                          </div>
                        </TableCell>
                        <TableCell>
                          {chargerId === "Unknown" ? (
                            <span className="text-sm text-muted-foreground">
                              Unknown
                            </span>
                          ) : (
                            <Link
                              to={`/monitoring/${chargerId}`}
                              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-primary hover:bg-accent"
                            >
                              {chargerId}
                              <ExternalLink className="h-3.5 w-3.5" />
                            </Link>
                          )}
                        </TableCell>
                        <TableCell>
                          <ModeBadge service={service} />
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {service.model_type || "Unknown"}
                        </TableCell>
                        <TableCell>
                          <div
                            className="flex max-w-[22rem] flex-wrap gap-1.5"
                            title={service.mqtt_topics.join(", ")}
                          >
                            {topicPreview.length > 0 ? (
                              <>
                                {topicPreview.map((topic) => (
                                  <span
                                    key={topic}
                                    className="max-w-[12rem] truncate rounded-full border bg-background px-2 py-1 font-mono text-[11px]"
                                  >
                                    {topic}
                                  </span>
                                ))}
                                {service.mqtt_topics.length > topicPreview.length ? (
                                  <span className="rounded-full bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                                    +{service.mqtt_topics.length - topicPreview.length}
                                  </span>
                                ) : null}
                              </>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                None
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <StatusBadge
                            label={status.label}
                            className={status.className}
                          />
                        </TableCell>
                        <TableCell>
                          <StageSummary service={service} />
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {service.created_at
                            ? new Date(service.created_at).toLocaleString()
                            : "Unknown"}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={() => deleteService(service)}
                            aria-label={deleteAction.ariaLabel}
                            className="text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
              </TableBody>
            </Table>
          ) : (
            <EmptyServicesState />
          )}
        </SectionPanel>
      </PageShell>
    </>
  );
}
