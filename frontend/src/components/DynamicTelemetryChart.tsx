import React, {
  useCallback,
  useEffect,
  useMemo,
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
import {
  buildTelemetryChartModel,
  buildTelemetryChartOption,
  formatChartTime,
  getLocalTimeZone,
  type ChartViewport,
} from "@/lib/telemetry-chart";
import { isWithinTimeRange } from "@/lib/time-utils";
import type { Anomaly, TelemetryTypeData } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";

interface DynamicTelemetryChartProps {
  telemetryData: TelemetryTypeData;
  anomalies?: Anomaly[];
  evidence?: MonitoringChartEvidence[];
}

const CATEGORY_COLORS: Record<string, string> = {
  cpu: "#0f9f8e",
  system: "#2563eb",
  controller: "#d97706",
  other: "#7c3aed",
};

const formatDisplayName = (value: string): string =>
  value
    .replace(/([A-Z])/gu, " $1")
    .replace(/^./u, (character) => character.toUpperCase())
    .trim();

const getLatestFiniteTime = (telemetryData: TelemetryTypeData): number | undefined => {
  const times = telemetryData.data
    .map(({ timestamp }) => Date.parse(timestamp))
    .filter(Number.isFinite);
  return times.length > 0 ? Math.max(...times) : undefined;
};

export const DynamicTelemetryChart: React.FC<DynamicTelemetryChartProps> = ({
  telemetryData,
  anomalies = [],
  evidence = [],
}) => {
  const { resolvedTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [fromDate, setFromDate] = useState<Date>();
  const [toDate, setToDate] = useState<Date>();
  const [viewport, setViewport] = useState<ChartViewport>({ mode: "live" });
  const [inspectionDataEndMs, setInspectionDataEndMs] = useState<number>();
  const [cardNode, setCardNode] = useState<HTMLDivElement | null>(null);
  const [isChartVisible, setIsChartVisible] = useState(
    () => typeof IntersectionObserver === "undefined",
  );

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

  const displayName = useMemo(
    () => formatDisplayName(telemetryData.type),
    [telemetryData.type],
  );
  const timeZone = useMemo(() => getLocalTimeZone(), []);
  const themeColors = useMemo(
    () => resolveChartThemeColors(resolvedTheme),
    [resolvedTheme],
  );

  const resetViewport = useCallback(() => {
    setViewport({ mode: "live" });
    setInspectionDataEndMs(undefined);
  }, []);

  const applyRelativeRange = useCallback(
    (hours: number) => {
      const maxTime = getLatestFiniteTime(telemetryData);
      if (maxTime === undefined) return;
      setFromDate(new Date(maxTime - hours * 60 * 60 * 1_000));
      setToDate(new Date(maxTime));
      resetViewport();
    },
    [resetViewport, telemetryData],
  );

  const handleFromDateChange = useCallback(
    (date: Date | undefined) => {
      setFromDate(date);
      setToDate((currentToDate) =>
        date && currentToDate && currentToDate.getTime() < date.getTime()
          ? date
          : currentToDate,
      );
      resetViewport();
    },
    [resetViewport],
  );

  const handleToDateChange = useCallback(
    (date: Date | undefined) => {
      setToDate(date);
      setFromDate((currentFromDate) =>
        date && currentFromDate && currentFromDate.getTime() > date.getTime()
          ? date
          : currentFromDate,
      );
      resetViewport();
    },
    [resetViewport],
  );

  const clearRange = useCallback(() => {
    setFromDate(undefined);
    setToDate(undefined);
    resetViewport();
  }, [resetViewport]);

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
  const telemetryEvidence = useMemo(
    () =>
      evidence.filter(
        (item) =>
          item.sensor_set.includes(telemetryData.type) &&
          isWithinTimeRange(item.timestamp, fromDate, toDate),
      ),
    [evidence, fromDate, telemetryData.type, toDate],
  );
  const shouldBuildChart = !collapsed && isChartVisible;
  const chartModel = useMemo(() => {
    if (!shouldBuildChart) return undefined;
    return buildTelemetryChartModel({
      telemetryName: displayName,
      telemetryUnit: telemetryData.unit,
      telemetryColor: CATEGORY_COLORS[telemetryData.category] ?? "#7c3aed",
      telemetry: filteredData,
      evidence: telemetryEvidence,
      anomalyZones: createAnomalyZones(telemetryAnomalies),
      anomalyMarkers: createAnomalyMarkers(filteredData, telemetryAnomalies),
    });
  }, [
    displayName,
    filteredData,
    shouldBuildChart,
    telemetryAnomalies,
    telemetryData.category,
    telemetryData.unit,
    telemetryEvidence,
  ]);
  const accessibleDescription = useMemo(() => {
    const pointCount = chartModel?.telemetry.data.length ?? 0;
    const secondaryCount = chartModel?.secondarySeries.length ?? 0;
    return `${displayName} telemetry chart with ${pointCount} points${secondaryCount > 0 ? ` and ${secondaryCount} sequential-evidence series in a linked lower pane` : ""}. Times are shown in ${timeZone}.`;
  }, [chartModel, displayName, timeZone]);
  const chartOption = useMemo(
    () =>
      chartModel
        ? buildTelemetryChartOption({
            model: chartModel,
            viewport,
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
      viewport,
    ],
  );

  const handleViewportChange = useCallback(
    (startMs: number, endMs: number) => {
      setViewport({ mode: "absolute", startMs, endMs });
      setInspectionDataEndMs((current) => current ?? chartModel?.extent?.[1]);
    },
    [chartModel?.extent],
  );
  const zoomIn = useCallback(() => {
    const extent = chartModel?.extent;
    if (!extent) return;
    const startMs = viewport.mode === "absolute" ? viewport.startMs : extent[0];
    const endMs = viewport.mode === "absolute" ? viewport.endMs : extent[1];
    const inset = (endMs - startMs) / 4;
    if (!Number.isFinite(inset) || inset <= 0) return;
    setViewport({
      mode: "absolute",
      startMs: startMs + inset,
      endMs: endMs - inset,
    });
    setInspectionDataEndMs((current) => current ?? extent[1]);
  }, [chartModel?.extent, viewport]);
  const hasNewData =
    viewport.mode === "absolute" &&
    inspectionDataEndMs !== undefined &&
    chartModel?.extent !== undefined &&
    chartModel.extent[1] > inspectionDataEndMs;
  const latestTelemetry = chartModel?.telemetry.data[
    chartModel.telemetry.data.length - 1
  ];

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
          {telemetryEvidence.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700 dark:text-emerald-300">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Restarted evidence
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
            <div className="h-[420px]" aria-hidden="true" />
          ) : filteredData.length === 0 ? (
            <div className="flex h-[420px] flex-col items-center justify-center rounded-lg border border-dashed bg-muted/20 p-6 text-center">
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
              <EChart
                option={chartOption}
                resolvedTheme={resolvedTheme}
                accessibleDescription={accessibleDescription}
                onViewportChange={handleViewportChange}
              />
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                {latestTelemetry && (
                  <span>
                    Current {displayName}: {latestTelemetry[1]}
                    {telemetryData.unit ? ` ${telemetryData.unit}` : ""} at{" "}
                    {formatChartTime(latestTelemetry[0], timeZone, "tooltip")}
                  </span>
                )}
                {chartModel.secondarySeries.map((series) => {
                  const latest = series.data[series.data.length - 1];
                  return latest ? (
                    <span key={series.id}>
                      {series.name}: {latest[1]}
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
