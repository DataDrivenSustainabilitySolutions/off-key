import { useState, useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity } from "lucide-react";

import {
  MetricCard,
  PageHeader,
  PageShell,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { useFetch } from "@/dataFetch/UseFetch";
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
import type { TelemetryTypeData } from "@/dataFetch/FetchContext";

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
      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground shadow-xs"
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

  // Import functions and data from FetchContext
  const {
    allTelemetryMap,
    anomaliesMap,
    loadAllTelemetryTypes,
    loadAnomalies,
  } = useFetch();

  // Loading states
  const [isLoadingTelemetry, setIsLoadingTelemetry] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  // Fetch dynamic telemetry data and anomalies
  useEffect(() => {
    if (!chargerId) return;

    // Load initial data with loading state tracking
    const loadInitialData = async () => {
      setIsLoadingTelemetry(true);

      try {
        await Promise.all([
          loadAllTelemetryTypes(chargerId).finally(() => setIsLoadingTelemetry(false)),
          loadAnomalies(chargerId),
        ]);
      } catch (error) {
        clientLogger.error({
          event: "details.initial_load_failed",
          message: "Error loading initial details data",
          error,
          context: { chargerId },
        });
        setIsLoadingTelemetry(false);
      }
    };

    loadInitialData();

    const interval = setInterval(() => {
      loadAllTelemetryTypes(chargerId);
      loadAnomalies(chargerId);
    }, INTERVALS.DETAILS_UPDATE); // every 10s

    // Cleanup on unmount or change
    return () => clearInterval(interval);
  }, [chargerId, loadAllTelemetryTypes, loadAnomalies]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setNow(Date.now());
    }, INTERVALS.DETAILS_UPDATE);

    return () => window.clearInterval(interval);
  }, []);

  // Get dynamic telemetry data and anomalies
  const allTelemetryData = useMemo(
    () => allTelemetryMap[resolvedChargerId] ?? [],
    [allTelemetryMap, resolvedChargerId]
  );
  const chargerAnomalies = anomaliesMap[resolvedChargerId] ?? [];
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

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
          <div>
            <h2 className="text-lg font-semibold">Telemetry</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Charts update automatically while this page is open.
            </p>
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
                  loadAllTelemetryTypes(resolvedChargerId).finally(() =>
                    setIsLoadingTelemetry(false)
                  );
                }}
              />
            </div>
          ) : (
            <div className="space-y-6">
              {telemetryByCategory.cpu.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-base font-semibold text-muted-foreground">CPU Metrics</h3>
                  {telemetryByCategory.cpu.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.system.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-base font-semibold text-muted-foreground">System Metrics</h3>
                  {telemetryByCategory.system.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.controller.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-base font-semibold text-muted-foreground">Controller Metrics</h3>
                  {telemetryByCategory.controller.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
                    />
                  ))}
                </div>
              )}

              {telemetryByCategory.other.length > 0 && (
                <div className="space-y-4">
                  <h3 className="text-base font-semibold text-muted-foreground">Other Metrics</h3>
                  {telemetryByCategory.other.map((telemetryData) => (
                    <DynamicTelemetryChart
                      key={telemetryData.type}
                      telemetryData={telemetryData}
                      chargerId={resolvedChargerId}
                      anomalies={chargerAnomalies}
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
