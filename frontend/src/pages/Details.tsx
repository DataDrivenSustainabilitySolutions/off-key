import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity, Link2, Unlink2 } from "lucide-react";

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
import {
  getAllTelemetryData,
  getAnomalies,
  mergeTelemetryData,
} from "@/lib/charger-api";
import type {
  MonitoringChartEvidence,
  MonitoringEvidenceCursor,
} from "@/types/monitoring";
import { useLinkedChartNavigation } from "@/hooks/use-linked-chart-navigation";
import {
  getMonitoringEvidenceCursor,
  mergeMonitoringChartEvidence,
} from "@/lib/monitoring-chart";
import type { Anomaly, TelemetryCursor, TelemetryTypeData } from "@/types/charger";

type TelemetryCategoryGroups = Record<
  TelemetryTypeData["category"],
  TelemetryTypeData[]
>;

const RECENT_TELEMETRY_WINDOW_MS = INTERVALS.DETAILS_UPDATE * 6;
const EVIDENCE_PAGE_SIZE = 2000;
const MAX_FORWARD_PAGES = 10;
const EMPTY_EVIDENCE: MonitoringChartEvidence[] = [];
const TELEMETRY_SECTIONS: Array<{
  category: TelemetryTypeData["category"];
  label: string;
}> = [
  { category: "cpu", label: "CPU Metrics" },
  { category: "system", label: "System Metrics" },
  { category: "controller", label: "Controller Metrics" },
  { category: "other", label: "Other Metrics" },
];

const sameAnomalyWindow = (left: Anomaly[], right: Anomaly[]): boolean =>
  left.length === right.length &&
  left.every((item, index) => item.anomaly_id === right[index]?.anomaly_id);

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

  const [isLoadingTelemetry, setIsLoadingTelemetry] = useState(true);
  const [allTelemetryData, setAllTelemetryData] = useState<TelemetryTypeData[]>([]);
  const [chargerAnomalies, setChargerAnomalies] = useState<Anomaly[]>([]);
  const [monitoringEvidence, setMonitoringEvidence] = useState<MonitoringChartEvidence[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [refreshRequest, setRefreshRequest] = useState(0);

  useEffect(() => {
    if (!chargerId) {
      return;
    }

    let cancelled = false;
    let refreshInFlight = false;
    let activeController: AbortController | undefined;
    let evidenceCursor: MonitoringEvidenceCursor | undefined;
    let evidenceLoaded = false;
    let telemetryLoaded = false;
    const telemetryCursors = new Map<string, TelemetryCursor>();

    const refresh = async (showLoading = false) => {
      if (refreshInFlight) return;
      refreshInFlight = true;
      const controller = new AbortController();
      activeController = controller;
      if (showLoading) setIsLoadingTelemetry(true);

      const loadEvidence = async () => {
        const initialCursor = evidenceCursor;
        let cursor = initialCursor;
        const evidence: MonitoringChartEvidence[] = [];
        for (let pageNumber = 0; pageNumber < MAX_FORWARD_PAGES; pageNumber += 1) {
          const page = await apiUtils.get<MonitoringChartEvidence[]>(
            API_CONFIG.ENDPOINTS.MONITORING.CHART_EVIDENCE(chargerId, cursor),
            { signal: controller.signal },
          );
          evidence.push(...page);
          if (!initialCursor || page.length < EVIDENCE_PAGE_SIZE) return evidence;
          const nextCursor = getMonitoringEvidenceCursor(page);
          if (
            !nextCursor ||
            (nextCursor.created === cursor?.created &&
              nextCursor.timestamp === cursor.timestamp &&
              nextCursor.service_id === cursor.service_id &&
              nextCursor.sequence_number === cursor.sequence_number)
          ) return evidence;
          cursor = nextCursor;
        }
        return evidence;
      };

      const [telemetryResult, anomaliesResult, evidenceResult] =
        await Promise.allSettled([
          telemetryLoaded
            ? getAllTelemetryData(
                chargerId,
                controller.signal,
                telemetryCursors,
              )
            : getAllTelemetryData(chargerId, controller.signal),
          getAnomalies(chargerId, controller.signal),
          loadEvidence(),
        ]);

      if (!cancelled) {
        if (telemetryResult.status === "fulfilled") {
          setAllTelemetryData((current) =>
            telemetryLoaded
              ? mergeTelemetryData(current, telemetryResult.value)
              : telemetryResult.value
          );
          telemetryLoaded = true;
          telemetryResult.value.forEach((series) => {
            if (series.cursor) telemetryCursors.set(series.type, series.cursor);
          });
        } else {
          clientLogger.error({
            event: "details.telemetry_load_failed",
            message: "Error loading charger telemetry",
            error: telemetryResult.reason,
            context: { chargerId },
          });
        }

        if (anomaliesResult.status === "fulfilled") {
          setChargerAnomalies((current) =>
            sameAnomalyWindow(current, anomaliesResult.value)
              ? current
              : anomaliesResult.value
          );
        } else {
          clientLogger.error({
            event: "details.anomalies_load_failed",
            message: "Error loading charger anomalies",
            error: anomaliesResult.reason,
            context: { chargerId },
          });
        }

        if (evidenceResult.status === "fulfilled") {
          const incomingEvidence = evidenceResult.value ?? [];
          setMonitoringEvidence((current) =>
            evidenceLoaded
              ? mergeMonitoringChartEvidence(current, incomingEvidence)
              : incomingEvidence
          );
          evidenceLoaded = true;
          evidenceCursor =
            getMonitoringEvidenceCursor(incomingEvidence) ?? evidenceCursor;
        } else {
          clientLogger.error({
            event: "details.monitoring_evidence_load_failed",
            message: "Error loading monitoring evidence",
            error: evidenceResult.reason,
            context: { chargerId },
          });
        }

        setNow(Date.now());

        if (showLoading) setIsLoadingTelemetry(false);
      }
      if (activeController === controller) activeController = undefined;
      refreshInFlight = false;
    };

    void refresh(true);
    const interval = window.setInterval(
      () => {
        if (!document.hidden) void refresh();
      },
      INTERVALS.DETAILS_UPDATE,
    );
    const handleVisibilityChange = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      activeController?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [chargerId, refreshRequest]);

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

  const evidenceByTelemetry = useMemo(() => {
    const grouped = new Map<string, MonitoringChartEvidence[]>();
    monitoringEvidence.forEach((item) => {
      item.sensor_set.forEach((sensor) => {
        const sensorEvidence = grouped.get(sensor) ?? [];
        sensorEvidence.push(item);
        grouped.set(sensor, sensorEvidence);
      });
    });
    return grouped;
  }, [monitoringEvidence]);

  const {
    chartsLinked,
    linkedTimelineExtent,
    getNavigationState,
    handleNavigationStateChange,
    toggleChartLink,
  } = useLinkedChartNavigation(allTelemetryData, monitoringEvidence);

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
            <div className="flex items-center gap-2">
              {allTelemetryData.length > 1 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant={chartsLinked ? "secondary" : "outline"}
                      size="sm"
                      className="h-8 gap-1.5 px-2.5 text-xs"
                      aria-label={
                        chartsLinked
                          ? "Unlink chart navigation"
                          : "Link chart navigation"
                      }
                      aria-pressed={chartsLinked}
                      onClick={toggleChartLink}
                    >
                      {chartsLinked ? (
                        <Link2 className="size-3.5" />
                      ) : (
                        <Unlink2 className="size-3.5" />
                      )}
                      {chartsLinked ? "Linked" : "Independent"}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top" align="end" className="max-w-64">
                    {chartsLinked
                      ? "Time ranges, pan, and zoom are shared. Vertical scales stay independent."
                      : "Link horizontal time navigation across every chart."}
                  </TooltipContent>
                </Tooltip>
              )}
              <span className="hidden rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground sm:inline-flex">
                Auto refresh
              </span>
            </div>
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
              {TELEMETRY_SECTIONS.map(({ category, label }) => {
                const telemetrySeries = telemetryByCategory[category];
                return telemetrySeries.length > 0 ? (
                  <div key={category} className="space-y-4">
                    <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {label}
                    </h3>
                    {telemetrySeries.map((telemetryData) => (
                      <DynamicTelemetryChart
                        key={telemetryData.type}
                        telemetryData={telemetryData}
                        anomalies={chargerAnomalies}
                        evidence={
                          evidenceByTelemetry.get(telemetryData.type) ?? EMPTY_EVIDENCE
                        }
                        navigationState={getNavigationState(telemetryData.type)}
                        timelineExtent={
                          chartsLinked ? linkedTimelineExtent : undefined
                        }
                        onNavigationStateChange={handleNavigationStateChange}
                      />
                    ))}
                  </div>
                ) : null;
              })}
            </div>
          )}
        </section>
      </PageShell>
    </>
  );
};
export default Details;
