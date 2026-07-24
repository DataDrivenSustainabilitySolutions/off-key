import { useState, useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity } from "lucide-react";

import {
  MetricCard,
  PageHeader,
  PageShell,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { ChartSkeleton, NoDataFound } from "@/components/LoadingStates";
import DynamicTelemetryChart from "@/components/DynamicTelemetryChart";
import { Button } from "@/components/ui/button";
import { INTERVALS } from "@/lib/constants";
import { clientLogger } from "@/lib/logger";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getAllTelemetryData, getAnomalies } from "@/lib/charger-api";
import type { MonitoringEvidence } from "@/types/monitoring";
import type { Anomaly, TelemetryTypeData } from "@/types/charger";

type TelemetryCategoryGroups = Record<
  TelemetryTypeData["category"],
  TelemetryTypeData[]
>;

const RECENT_TELEMETRY_WINDOW_MS = INTERVALS.DETAILS_UPDATE * 6;

const getLatestTelemetryTimestamp = (
  telemetryData: TelemetryTypeData[]
): number | undefined => {
  const timestamps = telemetryData
    .flatMap((telemetry) => telemetry.data.map((point) => Date.parse(point.timestamp)))
    .filter((timestamp) => Number.isFinite(timestamp));

  if (timestamps.length === 0) {
    return undefined;
  }

  return Math.max(...timestamps);
};

const LiveTelemetryIndicator: React.FC<{
  hasRecentTelemetry: boolean;
  hasTelemetry: boolean;
}> = ({ hasRecentTelemetry, hasTelemetry }) => {
  const label = hasRecentTelemetry
    ? "Live telemetry"
    : hasTelemetry
      ? "Telemetry ready"
      : "Waiting for telemetry";

  return (
    <div
      className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/70 bg-card px-3 text-sm text-muted-foreground shadow-xs"
      aria-label={label}
      title={label}
    >
      <span
        className={cn(
          "size-2.5 rounded-full",
          hasRecentTelemetry
            ? "live-pulse-ring bg-emerald-500"
            : hasTelemetry
              ? "bg-amber-400"
              : "bg-muted-foreground/50"
        )}
      />
      <span className="whitespace-nowrap">{label}</span>
    </div>
  );
};

const Details: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  const resolvedChargerId = chargerId ?? "";

  const [isLoadingTelemetry, setIsLoadingTelemetry] = useState(true);
  const [allTelemetryData, setAllTelemetryData] = useState<TelemetryTypeData[]>([]);
  const [chargerAnomalies, setChargerAnomalies] = useState<Anomaly[]>([]);
  const [monitoringEvidence, setMonitoringEvidence] = useState<MonitoringEvidence[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [refreshRequest, setRefreshRequest] = useState(0);

  useEffect(() => {
    if (!chargerId) {
      return;
    }

    let cancelled = false;
    let refreshInFlight = false;

    const refresh = async (showLoading = false) => {
      if (refreshInFlight) return;
      refreshInFlight = true;
      if (showLoading) setIsLoadingTelemetry(true);

      const [telemetryResult, anomaliesResult, evidenceResult] =
        await Promise.allSettled([
          getAllTelemetryData(chargerId),
          getAnomalies(chargerId),
          apiUtils.get<MonitoringEvidence[]>(
            API_CONFIG.ENDPOINTS.MONITORING.EVIDENCE(chargerId),
          ),
        ]);

      if (!cancelled) {
        if (telemetryResult.status === "fulfilled") {
          setAllTelemetryData(telemetryResult.value);
        } else {
          clientLogger.error({
            event: "details.telemetry_load_failed",
            message: "Error loading charger telemetry",
            error: telemetryResult.reason,
            context: { chargerId },
          });
        }

        if (anomaliesResult.status === "fulfilled") {
          setChargerAnomalies(anomaliesResult.value);
        } else {
          clientLogger.error({
            event: "details.anomalies_load_failed",
            message: "Error loading charger anomalies",
            error: anomaliesResult.reason,
            context: { chargerId },
          });
        }

        if (evidenceResult.status === "fulfilled") {
          setMonitoringEvidence(evidenceResult.value ?? []);
        } else {
          clientLogger.error({
            event: "details.monitoring_evidence_load_failed",
            message: "Error loading monitoring evidence",
            error: evidenceResult.reason,
            context: { chargerId },
          });
        }

        if (showLoading) setIsLoadingTelemetry(false);
      }
      refreshInFlight = false;
    };

    void refresh(true);
    const interval = window.setInterval(
      () => void refresh(),
      INTERVALS.DETAILS_UPDATE,
    );

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [chargerId, refreshRequest]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setNow(Date.now());
    }, INTERVALS.DETAILS_UPDATE);

    return () => window.clearInterval(interval);
  }, []);

  const latestTelemetryTimestamp = useMemo(
    () => getLatestTelemetryTimestamp(allTelemetryData),
    [allTelemetryData]
  );
  const latestTelemetryAgeMs =
    latestTelemetryTimestamp === undefined
      ? undefined
      : now - latestTelemetryTimestamp;
  const hasRecentTelemetry =
    latestTelemetryAgeMs !== undefined &&
    latestTelemetryAgeMs >= 0 &&
    latestTelemetryAgeMs <= RECENT_TELEMETRY_WINDOW_MS;

  // Group telemetry data by category for better organization
  const telemetryByCategory = useMemo(() => {
    const grouped: TelemetryCategoryGroups = {
      cpu: [],
      system: [],
      controller: [],
      other: [],
    };

    allTelemetryData.forEach(telemetry => {
      grouped[telemetry.category].push(telemetry);
    });

    return grouped;
  }, [allTelemetryData]);


  // No additional functions needed - all functionality is handled by DynamicTelemetryChart

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Charger Detail"
          title={`Charger ${chargerId}`}
          description="Review telemetry streams, recent anomaly overlays, and operational monitoring setup."
          actions={
            <>
              <LiveTelemetryIndicator
                hasRecentTelemetry={hasRecentTelemetry}
                hasTelemetry={latestTelemetryTimestamp !== undefined}
              />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button asChild>
                    <Link to={`/monitoring/${chargerId}`}>
                      <Activity className="h-4 w-4" />
                      Monitoring
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top" align="center">
                  Open Live Monitoring
                </TooltipContent>
              </Tooltip>
            </>
          }
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          <MetricCard
            label="Telemetry Series"
            value={allTelemetryData.length}
            helper="Available chart streams"
          />
          <MetricCard
            label="Anomalies"
            value={chargerAnomalies.length}
            helper="Loaded for this charger"
            tone={chargerAnomalies.length > 0 ? "warning" : "default"}
          />
          <MetricCard
            label="Categories"
            value={
              Object.values(telemetryByCategory).filter((group) => group.length > 0)
                .length
            }
            helper="With current data"
            tone="info"
          />
        </div>

        <section className="space-y-5">
          <div className="flex items-end justify-between gap-4 border-b border-border/60 pb-4">
            <div>
            <h2 className="text-lg font-semibold tracking-[-0.02em]">Telemetry</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Charts update automatically while this page is open.
            </p>
            </div>
            <span className="hidden rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground sm:inline-flex">
              Auto refresh
            </span>
          </div>

          {isLoadingTelemetry ? (
            <div className="space-y-4">
              <ChartSkeleton />
              <ChartSkeleton />
            </div>
          ) : allTelemetryData.length === 0 ? (
            <div className="h-80">
              <NoDataFound
                message="No telemetry data available for this charger"
                onRefresh={() => {
                  setIsLoadingTelemetry(true);
                  setRefreshRequest((request) => request + 1);
                }}
              />
            </div>
          ) : (
            <div className="space-y-6">
              {telemetryByCategory.cpu.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">CPU Metrics</h3>
                  {telemetryByCategory.cpu.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                      evidence={monitoringEvidence}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.system.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">System Metrics</h3>
                  {telemetryByCategory.system.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                      evidence={monitoringEvidence}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.controller.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">Controller Metrics</h3>
                  {telemetryByCategory.controller.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                      evidence={monitoringEvidence}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.other.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">Other Metrics</h3>
                  {telemetryByCategory.other.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                      evidence={monitoringEvidence}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </PageShell>
    </>
  );
};
export default Details;
