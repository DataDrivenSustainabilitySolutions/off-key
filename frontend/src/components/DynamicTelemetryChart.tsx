import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronDown } from "lucide-react";

import DateTimePicker from "@/components/DateTimePicker";
import { EChart } from "@/components/EChart";
import { NoChartsAvailable } from "@/components/LoadingStates";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import {
  createAnomalyMarkers,
  createAnomalyZones,
  filterAnomalies,
} from "@/lib/anomaly-utils";
import { resolveChartThemeColors } from "@/lib/echarts-theme";
import { getEvidenceTimeForSensor } from "@/lib/monitoring-chart";
import {
  buildTelemetryChartModel,
  buildTelemetryChartOption,
  DEFAULT_CHART_NAVIGATION,
  formatChartTime,
  formatNumber,
  getLocalTimeZone,
  areChartNavigationStatesEqual,
  type ChartNavigationState,
} from "@/lib/telemetry-chart";
import { isWithinTimeRange } from "@/lib/time-utils";
import type { Anomaly, TelemetryTypeData } from "@/types/charger";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";

interface DynamicTelemetryChartProps {
  telemetryData: TelemetryTypeData;
  anomalies?: Anomaly[];
  evidence?: MonitoringChartEvidence[];
  monitoringService?: ActiveService;
  navigationState?: ChartNavigationState;
  timelineExtent?: readonly [startMs: number, endMs: number];
  onNavigationStateChange?: (
    telemetryType: string,
    state: ChartNavigationState,
  ) => void;
}

const formatDisplayName = (value: string): string =>
  value
    .replace(/([A-Z])/gu, " $1")
    .replace(/^./u, (character) => character.toUpperCase())
    .trim();

const formatOperationalStage = (stage: string): string =>
  stage.replace(/_/gu, " ");
const formatSeriesKindForData = (kind: string): string => kind.replace(/_/gu, "-");

const getLatestFiniteTime = (telemetryData: TelemetryTypeData): number | undefined => {
  const times = telemetryData.data
    .map(({ timestamp }) => Date.parse(timestamp))
    .filter(Number.isFinite);
  return times.length > 0 ? Math.max(...times) : undefined;
};

const compareEvidenceCursor = (
  left: MonitoringChartEvidence,
  right: MonitoringChartEvidence,
): boolean => {
  const leftCreated = Date.parse(left.timestamp);
  const rightCreated = Date.parse(right.timestamp);
  if (!Number.isFinite(leftCreated) || !Number.isFinite(rightCreated)) {
    return rightCreated > leftCreated;
  }
  if (leftCreated !== rightCreated) return leftCreated < rightCreated;
  if (left.sequence_number !== right.sequence_number) {
    return left.sequence_number < right.sequence_number;
  }
  return left.service_id.localeCompare(right.service_id) < 0;
};

export const DynamicTelemetryChart: React.FC<DynamicTelemetryChartProps> = ({
  telemetryData,
  anomalies = [],
  evidence = [],
  monitoringService,
  navigationState,
  timelineExtent,
  onNavigationStateChange,
}) => {
  const { resolvedTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [localNavigationState, setLocalNavigationState] =
    useState<ChartNavigationState>(DEFAULT_CHART_NAVIGATION);
  const [cardNode, setCardNode] = useState<HTMLDivElement | null>(null);
  const [isChartVisible, setIsChartVisible] = useState(
    () => typeof IntersectionObserver === "undefined",
  );
  const rafIdRef = useRef<number | undefined>(undefined);
  const pendingViewportRef = useRef<{ startMs: number; endMs: number } | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined" || !cardNode) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        if (entry) setIsChartVisible(entry.isIntersecting);
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(cardNode);
    return () => observer.disconnect();
  }, [cardNode]);

  useEffect(() => {
    return () => {
      if (rafIdRef.current !== undefined) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = undefined;
      }
    };
  }, []);

  const displayName = useMemo(
    () => formatDisplayName(telemetryData.type),
    [telemetryData.type],
  );
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const themeColors = useMemo(
    () => resolveChartThemeColors(resolvedTheme),
    [resolvedTheme],
  );

  const activeNavigationState = navigationState ?? localNavigationState;
  const { viewport } = activeNavigationState;
  const fromDate = useMemo(
    () =>
      activeNavigationState.range.fromMs === undefined
        ? undefined
        : new Date(activeNavigationState.range.fromMs),
    [activeNavigationState.range.fromMs],
  );
  const toDate = useMemo(
    () =>
      activeNavigationState.range.toMs === undefined
        ? undefined
        : new Date(activeNavigationState.range.toMs),
    [activeNavigationState.range.toMs],
  );

  const commitNavigationState = useCallback(
    (nextState: ChartNavigationState) => {
      setLocalNavigationState((current) =>
        areChartNavigationStatesEqual(current, nextState) ? current : nextState,
      );
      onNavigationStateChange?.(telemetryData.type, nextState);
    },
    [onNavigationStateChange, telemetryData.type],
  );

  const resetViewport = useCallback(() => {
    commitNavigationState({
      range: activeNavigationState.range,
      viewport: { mode: "live" },
    });
  }, [activeNavigationState, commitNavigationState]);

  const applyRelativeRange = useCallback(
    (hours: number) => {
      const maxTime = getLatestFiniteTime(telemetryData);
      if (maxTime === undefined) return;
      commitNavigationState({
        range: {
          fromMs: maxTime - hours * 60 * 60 * 1_000,
          toMs: maxTime,
        },
        viewport: { mode: "live" },
      });
    },
    [commitNavigationState, telemetryData],
  );

  const handleFromDateChange = useCallback(
    (date: Date | undefined) => {
      const fromMs = date?.getTime();
      const currentToMs = activeNavigationState.range.toMs;
      commitNavigationState({
        range: {
          ...(fromMs !== undefined && { fromMs }),
          ...(currentToMs !== undefined && {
            toMs:
              fromMs !== undefined && currentToMs < fromMs
                ? fromMs
                : currentToMs,
          }),
        },
        viewport: { mode: "live" },
      });
    },
    [activeNavigationState.range.toMs, commitNavigationState],
  );

  const handleToDateChange = useCallback(
    (date: Date | undefined) => {
      const toMs = date?.getTime();
      const currentFromMs = activeNavigationState.range.fromMs;
      commitNavigationState({
        range: {
          ...(currentFromMs !== undefined && {
            fromMs:
              toMs !== undefined && currentFromMs > toMs
                ? toMs
                : currentFromMs,
          }),
          ...(toMs !== undefined && { toMs }),
        },
        viewport: { mode: "live" },
      });
    },
    [activeNavigationState.range.fromMs, commitNavigationState],
  );

  const clearRange = useCallback(() => {
    commitNavigationState(DEFAULT_CHART_NAVIGATION);
  }, [commitNavigationState]);

  const filteredData = useMemo(
    () =>
      telemetryData.data.filter(({ timestamp }) =>
        isWithinTimeRange(timestamp, fromDate, toDate),
      ),
    [telemetryData.data, fromDate, toDate],
  );
  const telemetryAnomalies = useMemo(
    () => filterAnomalies(anomalies, telemetryData.type, fromDate, toDate),
    [anomalies, fromDate, telemetryData.type, toDate],
  );
  const sensorEvidence = useMemo(
    () =>
      evidence.filter(
        (item) => item.sensor_set.includes(telemetryData.type),
      ),
    [evidence, telemetryData.type],
  );
  const telemetryEvidenceInRange = useMemo(
    () =>
      sensorEvidence.filter((item) => {
        const time = getEvidenceTimeForSensor(item, telemetryData.type);
        return (
          time !== undefined &&
          isWithinTimeRange(new Date(time).toISOString(), fromDate, toDate)
        );
      }),
    [fromDate, sensorEvidence, telemetryData.type, toDate],
  );
  const telemetryEvidenceByService = useMemo(() => {
    const buckets = new Map<string, MonitoringChartEvidence[]>();
    sensorEvidence.forEach((item) => {
      const bucket = buckets.get(item.service_id);
      if (bucket) {
        bucket.push(item);
      } else {
        buckets.set(item.service_id, [item]);
      }
    });
    return buckets;
  }, [sensorEvidence]);
  const telemetryEvidenceByServiceInRange = useMemo(() => {
    const buckets = new Map<string, MonitoringChartEvidence[]>();
    telemetryEvidenceInRange.forEach((item) => {
      const bucket = buckets.get(item.service_id);
      if (bucket) {
        bucket.push(item);
      } else {
        buckets.set(item.service_id, [item]);
      }
    });
    return buckets;
  }, [telemetryEvidenceInRange]);
  const selectedEvidenceServiceId = useMemo(() => {
    if (telemetryEvidenceByService.size === 0) return undefined;
    const monitoringEvidence =
      monitoringService?.id
        ? telemetryEvidenceByService.get(monitoringService.id)
        : undefined;
    if (
      monitoringService?.id &&
      monitoringEvidence !== undefined &&
      monitoringEvidence.length > 0
    ) {
      return monitoringService.id;
    }

    let adaptiveServiceId: string | undefined;
    let adaptiveEvidence: MonitoringChartEvidence | undefined;
    let fallbackServiceId: string | undefined;
    let fallbackEvidence: MonitoringChartEvidence | undefined;

    for (const [serviceId, evidence] of telemetryEvidenceByServiceInRange) {
      let latestEvidence: MonitoringChartEvidence | undefined;
      let latestAdaptiveEvidence: MonitoringChartEvidence | undefined;
      for (const item of evidence) {
        if (!latestEvidence || compareEvidenceCursor(latestEvidence, item)) {
          latestEvidence = item;
        }
        if (
          item.strategy === "adaptive_stream" &&
          (!latestAdaptiveEvidence ||
            compareEvidenceCursor(latestAdaptiveEvidence, item))
        ) {
          latestAdaptiveEvidence = item;
        }
      }
      if (!latestEvidence) continue;

      if (
        latestAdaptiveEvidence &&
        (!adaptiveEvidence ||
          compareEvidenceCursor(adaptiveEvidence, latestAdaptiveEvidence))
      ) {
        adaptiveEvidence = latestAdaptiveEvidence;
        adaptiveServiceId = serviceId;
      } else if (
        !fallbackEvidence ||
        compareEvidenceCursor(fallbackEvidence, latestEvidence)
      ) {
        fallbackEvidence = latestEvidence;
        fallbackServiceId = serviceId;
      }
    }

    return adaptiveServiceId ?? fallbackServiceId;
  }, [monitoringService, telemetryEvidenceByService, telemetryEvidenceByServiceInRange]);
  const operationalEvidence = useMemo(
    () =>
      selectedEvidenceServiceId
        ? sensorEvidence.filter((item) =>
            item.service_id === selectedEvidenceServiceId,
          )
        : [],
    [sensorEvidence, selectedEvidenceServiceId],
  );
  const telemetryEvidence = operationalEvidence;
  const latestOperationalEvidenceTime = useMemo(() => {
    const times = operationalEvidence
      .map((item) => getEvidenceTimeForSensor(item, telemetryData.type))
      .filter((time): time is number => time !== undefined);
    return times.length > 0 ? Math.max(...times) : undefined;
  }, [operationalEvidence, telemetryData.type]);
  const serviceIsOperational = Boolean(
    monitoringService?.status &&
    monitoringService.operational_status.stage === "operational" &&
    !monitoringService.operational_status.is_stale,
  );
  const awaitingFirstScore =
    serviceIsOperational && latestOperationalEvidenceTime === undefined;
  const pendingTelemetryTimestamps = useMemo(
    () =>
      serviceIsOperational && latestOperationalEvidenceTime !== undefined
        ? filteredData
            .map(({ timestamp }) => Date.parse(timestamp))
            .filter(
              (time) =>
                Number.isFinite(time) && time > latestOperationalEvidenceTime,
            )
        : [],
    [filteredData, latestOperationalEvidenceTime, serviceIsOperational],
  );
  const shouldBuildChart = !collapsed && isChartVisible;
  const chartModel = useMemo(() => {
    if (!shouldBuildChart) return undefined;
    return buildTelemetryChartModel({
      telemetryType: telemetryData.type,
      telemetryName: displayName,
      telemetryUnit: telemetryData.unit,
      telemetryColor: themeColors.primary,
      telemetry: filteredData,
      evidence: telemetryEvidence,
      pendingTelemetryTimestamps,
      anomalyZones: createAnomalyZones(telemetryAnomalies),
      anomalyMarkers: createAnomalyMarkers(filteredData, telemetryAnomalies),
    });
  }, [
    displayName,
    filteredData,
    shouldBuildChart,
    telemetryAnomalies,
    telemetryData.type,
    telemetryData.unit,
    telemetryEvidence,
    pendingTelemetryTimestamps,
    themeColors.primary,
  ]);
  const accessibleDescription = useMemo(() => {
    const pointCount = chartModel?.telemetry.data.length ?? 0;
    const staticCount = chartModel?.secondarySeries.filter((series) => series.pane === "static").length ?? 0;
    const adaptiveCount = chartModel?.secondarySeries.filter((series) => series.pane === "adaptive").length ?? 0;
    const pendingCount = chartModel?.pendingTelemetry.length ?? 0;
    return `${displayName} telemetry chart with ${pointCount} points${staticCount ? `, ${staticCount} logarithmic static-evidence series` : ""}${adaptiveCount ? `, and ${adaptiveCount} linear adaptive score and threshold series` : ""}${pendingCount ? `, with ${pendingCount} observations awaiting anomaly scores` : ""}. Evidence panes share the telemetry time axis. Times are shown in ${timeZone}.`;
  }, [chartModel, displayName, timeZone]);
  const chartOption = useMemo(
    () =>
      chartModel
        ? buildTelemetryChartOption({
            model: chartModel,
            viewport,
            timelineExtent,
            timeZone,
            colors: themeColors,
            accessibleDescription,
          })
        : undefined,
    [
      accessibleDescription,
      chartModel,
      themeColors,
      timeZone,
      timelineExtent,
      viewport,
    ],
  );

  const handleViewportChange = useCallback(
    (startMs: number, endMs: number) => {
      pendingViewportRef.current = { startMs, endMs };
      if (rafIdRef.current !== undefined) return;

      commitNavigationState({
        ...activeNavigationState,
        viewport: { mode: "absolute", startMs, endMs },
        inspectionDataEndMs:
          activeNavigationState.inspectionDataEndMs ??
          (timelineExtent ?? chartModel?.extent)?.[1],
      });

      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = undefined;
        const pending = pendingViewportRef.current;
        pendingViewportRef.current = null;
        if (!pending) return;
        commitNavigationState({
          ...activeNavigationState,
          viewport: { mode: "absolute", startMs: pending.startMs, endMs: pending.endMs },
          inspectionDataEndMs:
            activeNavigationState.inspectionDataEndMs ??
            (timelineExtent ?? chartModel?.extent)?.[1],
        });
      });
    },
    [
      activeNavigationState,
      chartModel?.extent,
      commitNavigationState,
      timelineExtent,
    ],
  );
  const zoomIn = useCallback(() => {
    const extent = timelineExtent ?? chartModel?.extent;
    if (!extent) return;
    const startMs = viewport.mode === "absolute" ? viewport.startMs : extent[0];
    const endMs = viewport.mode === "absolute" ? viewport.endMs : extent[1];
    const inset = (endMs - startMs) / 4;
    if (!Number.isFinite(inset) || inset <= 0) return;
    commitNavigationState({
      ...activeNavigationState,
      viewport: {
        mode: "absolute",
        startMs: startMs + inset,
        endMs: endMs - inset,
      },
      inspectionDataEndMs:
        activeNavigationState.inspectionDataEndMs ?? extent[1],
    });
  }, [
    activeNavigationState,
    chartModel?.extent,
    commitNavigationState,
    timelineExtent,
    viewport,
  ]);
  const hasNewData =
    viewport.mode === "absolute" &&
    activeNavigationState.inspectionDataEndMs !== undefined &&
    chartModel?.extent !== undefined &&
    chartModel.extent[1] > activeNavigationState.inspectionDataEndMs;
  const latestTelemetry = chartModel?.telemetry.data[
    chartModel.telemetry.data.length - 1
  ];

  const hasStaticPane = useMemo(
    () => telemetryEvidence.some((item) => item.strategy !== "adaptive_stream"),
    [telemetryEvidence],
  );
  const hasAdaptivePane = useMemo(
    () => telemetryEvidence.some((item) => item.strategy === "adaptive_stream"),
    [telemetryEvidence],
  );
  const paneCount = 1 + (hasStaticPane ? 1 : 0) + (hasAdaptivePane ? 1 : 0);
  const chartHeightPx = paneCount === 3 ? 680 : paneCount === 2 ? 520 : 420;
  const chartHeightClass =
    paneCount === 3 ? "h-[680px]" : paneCount === 2 ? "h-[520px]" : "h-[420px]";

  if (telemetryData.data.length === 0) {
    return (
      <Card
        ref={setCardNode}
        className="w-full overflow-hidden border-border/80 py-0 shadow-xs transition-all duration-300"
      >
        <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
          <CardTitle className="text-base">{displayName}</CardTitle>
          <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium capitalize text-muted-foreground">
            {telemetryData.category}
          </span>
        </div>
        <CardContent>
          <NoChartsAvailable />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      ref={setCardNode}
      className={`w-full overflow-hidden py-0 transition-all duration-300 ${collapsed ? "" : "min-h-96"}`}
    >
      <div
        className={`flex gap-3 border-b border-border/60 bg-muted/[0.12] px-5 py-4 ${collapsed ? "flex-row items-center justify-between" : "flex-col lg:flex-row lg:items-center lg:justify-between"}`}
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <CardTitle
            className={`${collapsed ? "whitespace-normal break-words" : "truncate"} text-base`}
          >
            {displayName}
          </CardTitle>
          <span className="rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {telemetryData.category}
          </span>
          {telemetryEvidence.some((item) => item.strategy !== "adaptive_stream") && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700 dark:text-emerald-300">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Restarted evidence
            </span>
          )}
          {telemetryEvidence.some((item) => item.strategy === "adaptive_stream") && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/20 bg-violet-500/[0.07] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-violet-700 dark:text-violet-300">
              <span className="size-1.5 rounded-full bg-violet-500" />
              Adaptive scores
            </span>
          )}
          {monitoringService && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {awaitingFirstScore
                ? "Awaiting first score"
                : `Monitoring: ${formatOperationalStage(
                    monitoringService.operational_status.stage,
                  )}`}
            </span>
          )}
          {pendingTelemetryTimestamps.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/[0.07] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-700 dark:text-amber-300">
              {pendingTelemetryTimestamps.length} awaiting score
            </span>
          )}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {!collapsed && (
            <div className="flex min-w-0 flex-wrap items-end gap-2 rounded-xl border border-border/70 bg-card p-2.5 shadow-xs">
              <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="min-w-0 space-y-1">
                  <span className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    From
                  </span>
                  <DateTimePicker
                    value={fromDate}
                    onChange={handleFromDateChange}
                    placeholder="Start"
                    ariaLabel="From date and time"
                    className="h-8 w-full min-w-[10.5rem] text-xs sm:w-[10.5rem]"
                  />
                </label>
                <label className="min-w-0 space-y-1">
                  <span className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    To
                  </span>
                  <DateTimePicker
                    value={toDate}
                    onChange={handleToDateChange}
                    placeholder="End"
                    ariaLabel="To date and time"
                    className="h-8 w-full min-w-[10.5rem] text-xs sm:w-[10.5rem]"
                  />
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => applyRelativeRange(24)}
                >
                  Past 24 hours
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => applyRelativeRange(1)}
                >
                  Past hour
                </Button>
                {(fromDate || toDate) && (
                  <Button type="button" variant="ghost" size="sm" onClick={clearRange}>
                    Clear
                  </Button>
                )}
              </div>
              <span className="basis-full text-[11px] text-muted-foreground">
                Local time zone: {timeZone}
              </span>
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setCollapsed((current) => !current)}
            aria-label={collapsed ? "Expand chart" : "Collapse chart"}
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform ${collapsed ? "rotate-180" : ""}`}
            />
          </Button>
        </div>
      </div>

      {!collapsed && (
        <CardContent className="pb-5 pt-5">
          {!isChartVisible ? (
            <div className={chartHeightClass} aria-hidden="true" />
          ) : filteredData.length === 0 ? (
            <div className={`flex ${chartHeightClass} flex-col items-center justify-center rounded-lg border border-dashed bg-muted/20 p-6 text-center`}>
              <p className="text-sm font-medium">No data in selected range</p>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                Adjust the From/To values or clear the range to show all available
                telemetry.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={clearRange}
                className="mt-4"
              >
                Clear range
              </Button>
            </div>
          ) : chartOption && chartModel ? (
            <>
              <div
                className="mb-2 flex flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground"
                aria-live="polite"
              >
                <Button type="button" variant="ghost" size="sm" onClick={zoomIn}>
                  Zoom in
                </Button>
                {viewport.mode === "absolute" && (
                  <>
                    <span>
                      {hasNewData ? "New data available" : "Inspection paused"}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={resetViewport}
                    >
                      Return to live
                    </Button>
                  </>
                )}
              </div>
              <div
                data-testid="telemetry-chart-container"
                data-chart-pane-count={paneCount}
                data-chart-height-px={chartHeightPx}
                className="w-full"
              >
                <EChart
                  option={chartOption}
                  resolvedTheme={resolvedTheme}
                  accessibleDescription={accessibleDescription}
                  onViewportChange={handleViewportChange}
                  className={`${chartHeightClass} w-full min-w-0 touch-none`}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                {latestTelemetry && (
                  <span>
                    Current {displayName}: {latestTelemetry[1]}
                    {telemetryData.unit ? ` ${telemetryData.unit}` : ""} at{" "}
                    {formatChartTime(latestTelemetry[0], timeZone, "tooltip")}
                  </span>
                )}
                {chartModel.secondarySeries.map((series) => {
                  const latest = [...series.data]
                    .reverse()
                    .find(([, value]) => value !== null);
                  return latest ? (
                    <span
                      key={series.id}
                      data-testid="telemetry-series-value"
                      data-series-id={series.id}
                      data-series-kind={formatSeriesKindForData(series.kind)}
                      data-series-service-id={series.serviceId}
                      data-series-name={series.name}
                    >
                      {series.name}: {formatNumber(latest[1] as number)}
                    </span>
                  ) : null;
                })}
              </div>
            </>
          ) : null}
        </CardContent>
      )}
    </Card>
  );
};

export default React.memo(DynamicTelemetryChart);
