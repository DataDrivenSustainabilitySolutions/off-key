import React, { useCallback, useMemo, useState } from 'react';
import { Card, CardContent, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import DateTimePicker from '@/components/DateTimePicker';
import { ChevronDown } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
} from 'recharts';
import { createAnomalyZones, filterAnomalies, hasAnomaly, getAnomalyStyle, createAnomalyTooltip } from '@/lib/anomaly-utils';
import type { Anomaly, TelemetryTypeData } from '@/types/charger';
import { formatTimestamp, isWithinTimeRange } from '@/lib/time-utils';
import { NoChartsAvailable } from '@/components/LoadingStates';
import type { MonitoringEvidence } from '@/types/monitoring';
import {
  buildMonitoringChartData,
  getMonitoringEvidenceSeries,
} from '@/lib/monitoring-chart';

type ChartDotProps = {
  cx?: number;
  cy?: number;
  payload?: {
    timestamp?: string;
  };
};

interface DynamicTelemetryChartProps {
  telemetryData: TelemetryTypeData;
  chargerId: string;
  anomalies?: Anomaly[];
  evidence?: MonitoringEvidence[];
}

const CATEGORY_COLORS: Record<string, string> = {
  cpu: '#0f9f8e',
  system: '#2563eb',
  controller: '#d97706',
  other: '#7c3aed',
};

const EVIDENCE_COLORS = ['#059669', '#7c3aed', '#dc2626', '#0284c7'];

export const DynamicTelemetryChart: React.FC<DynamicTelemetryChartProps> = ({
  telemetryData,
  anomalies = [],
  evidence = [],
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [fromDate, setFromDate] = useState<Date>();
  const [toDate, setToDate] = useState<Date>();

  // Format the telemetry type name for display
  const displayName = useMemo(() => {
    return telemetryData.type
      .replace(/([A-Z])/g, ' $1') // Add spaces before capital letters
      .replace(/^./, str => str.toUpperCase()) // Capitalize first letter
      .trim();
  }, [telemetryData.type]);

  // Get category color for the chart line
  const getCategoryColor = (category: string): string => {
    return CATEGORY_COLORS[category] ?? '#0f9f8e';
  };

  const applyRelativeRange = useCallback((hours: number) => {
    if (telemetryData.data.length === 0) return;
    const times = telemetryData.data.map(d => new Date(d.timestamp).getTime());
    const maxTime = Math.max(...times);
    const minTime = maxTime - hours * 60 * 60 * 1000;
    setFromDate(new Date(minTime));
    setToDate(new Date(maxTime));
  }, [telemetryData.data]);

  const handleFromDateChange = useCallback((date: Date | undefined) => {
    setFromDate(date);
    setToDate((currentToDate) => {
      if (date && currentToDate && currentToDate.getTime() < date.getTime()) {
        return date;
      }
      return currentToDate;
    });
  }, []);

  const handleToDateChange = useCallback((date: Date | undefined) => {
    setToDate(date);
    setFromDate((currentFromDate) => {
      if (date && currentFromDate && currentFromDate.getTime() > date.getTime()) {
        return date;
      }
      return currentFromDate;
    });
  }, []);

  const lastDay = useCallback(() => applyRelativeRange(24), [applyRelativeRange]);
  const lastHour = useCallback(() => applyRelativeRange(1), [applyRelativeRange]);
  const clearRange = useCallback(() => {
    setFromDate(undefined);
    setToDate(undefined);
  }, []);

  // Filter data based on date range
  const filteredData = useMemo(() => {
    return telemetryData.data.filter(item => {
      if (!fromDate && !toDate) return true;
      return isWithinTimeRange(item.timestamp, fromDate, toDate);
    });
  }, [telemetryData.data, fromDate, toDate]);

  // Filter anomalies for this telemetry type
  const telemetryAnomalies = useMemo(() =>
    filterAnomalies(anomalies, telemetryData.type, fromDate, toDate),
    [anomalies, telemetryData.type, fromDate, toDate]
  );

  // Create anomaly zones
  const anomalyZones = useMemo(() =>
    createAnomalyZones(telemetryAnomalies),
    [telemetryAnomalies]
  );
  const telemetryEvidence = useMemo(
    () => evidence.filter((item) =>
      item.sensor_set.includes(telemetryData.type) &&
      isWithinTimeRange(item.timestamp, fromDate, toDate)
    ),
    [evidence, telemetryData.type, fromDate, toDate]
  );
  const chartData = useMemo(
    () => buildMonitoringChartData(filteredData, telemetryEvidence),
    [filteredData, telemetryEvidence]
  );
  const evidenceSeries = useMemo(
    () => getMonitoringEvidenceSeries(telemetryEvidence),
    [telemetryEvidence]
  );
  const evidenceThresholds = useMemo(
    () => [...new Set(evidenceSeries.map((series) => series.threshold))],
    [evidenceSeries]
  );

  if (telemetryData.data.length === 0) {
    return (
      <Card className="w-full overflow-hidden border-border/80 py-0 shadow-xs transition-all duration-300">
        <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
          <CardTitle className="text-base">{displayName}</CardTitle>
          <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium capitalize text-muted-foreground">
            {telemetryData.category}
          </span>
          {telemetryEvidence.length > 0 && (
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              E-process
            </span>
          )}
        </div>
        <CardContent>
          <NoChartsAvailable />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={`w-full overflow-hidden py-0 transition-all duration-300 ${collapsed ? '' : 'min-h-96'}`}>
      <div className={`flex gap-3 border-b border-border/60 bg-muted/[0.12] px-5 py-4 ${collapsed ? 'flex-row items-center justify-between' : 'flex-col lg:flex-row lg:items-center lg:justify-between'}`}>
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <CardTitle className={`${collapsed ? 'whitespace-normal break-words' : 'truncate'} text-base`}>
            {displayName}
          </CardTitle>
          <span className="rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {telemetryData.category}
          </span>
          {telemetryEvidence.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700 dark:text-emerald-300">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Evidence
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
                <Button type="button" variant="outline" size="sm" onClick={lastDay}>
                  Past 24 hours
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={lastHour}>
                  Past hour
                </Button>
                {(fromDate || toDate) && (
                  <Button type="button" variant="ghost" size="sm" onClick={clearRange}>
                    Clear
                  </Button>
                )}
              </div>
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expand chart" : "Collapse chart"}
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform ${collapsed ? 'rotate-180' : ''}`}
            />
          </Button>
        </div>
      </div>

      {!collapsed && (
        <CardContent className="pb-5 pt-5">
          {filteredData.length === 0 ? (
            <div className="flex h-[300px] flex-col items-center justify-center rounded-lg border border-dashed bg-muted/20 p-6 text-center">
              <p className="text-sm font-medium">No data in selected range</p>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                Adjust the From/To values or clear the range to show all available telemetry.
              </p>
              <Button type="button" variant="outline" size="sm" onClick={clearRange} className="mt-4">
                Clear range
              </Button>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart
                data={chartData}
                margin={{
                  top: 5,
                  right: 30,
                  left: 20,
                  bottom: 5,
                }}
              >
                <CartesianGrid vertical={false} strokeDasharray="4 6" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="time"
                  type="number"
                  scale="time"
                  domain={['dataMin', 'dataMax']}
                  tickFormatter={(value) =>
                    formatTimestamp(new Date(Number(value)).toISOString())
                  }
                  tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: "hsl(var(--border))" }}
                />
                <YAxis
                  yAxisId="telemetry"
                  dataKey="value"
                  tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                {telemetryEvidence.length > 0 && (
                  <YAxis
                    yAxisId="evidence"
                    orientation="right"
                    scale="log"
                    domain={[0.000001, 'auto']}
                    tickFormatter={(value) => Number(value).toPrecision(2)}
                    allowDataOverflow
                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                )}
                <Tooltip
                  labelFormatter={(value) =>
                    formatTimestamp(new Date(Number(value)).toISOString())
                  }
                  contentStyle={{
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "12px",
                    background: "hsl(var(--popover))",
                    boxShadow: "0 12px 32px hsl(220 20% 10% / 0.08)",
                    fontSize: "12px",
                  }}
                />

                {evidenceThresholds.map((threshold) => (
                  <ReferenceLine
                    key={threshold}
                    yAxisId="evidence"
                    y={threshold}
                    stroke="#dc2626"
                    strokeDasharray="6 4"
                    label={{ value: `Ville ${threshold}`, position: 'insideTopRight' }}
                  />
                ))}

                {anomalyZones.map((zone, index) => (
                  <ReferenceArea
                    key={index}
                    x1={zone.start}
                    x2={zone.end}
                    strokeOpacity={0}
                    fill="red"
                    fillOpacity={0.1}
                  />
                ))}

                <Line
                  yAxisId="telemetry"
                  type="monotone"
                  dataKey="value"
                  connectNulls
                  stroke={getCategoryColor(telemetryData.category)}
                  strokeWidth={2.25}
                  activeDot={false}
                  dot={(props) => {
                    const { cx, cy, payload } = props as ChartDotProps;
                    const timestamp = payload?.timestamp;
                    if (!timestamp) {
                      return <></>;
                    }

                    const anomaly = hasAnomaly(timestamp, telemetryAnomalies);
                    if (anomaly && cx !== undefined && cy !== undefined) {
                      const style = getAnomalyStyle(anomaly.anomaly_type);
                      return (
                        <g key={`anomaly-${timestamp}`}>
                          <circle
                            cx={cx}
                            cy={cy}
                            r={style.radius}
                            fill={style.color}
                            stroke="darkred"
                            strokeWidth={1}
                            opacity={style.opacity}
                          />
                          <title>{createAnomalyTooltip(anomaly)}</title>
                        </g>
                      );
                    }
                    return <></>;
                  }}
                />
                {evidenceSeries.map((series, index) => (
                  <Line
                    key={series.serviceId}
                    yAxisId="evidence"
                    type="monotone"
                    dataKey={series.dataKey}
                    name={`Martingale ${series.serviceId.slice(0, 8)}`}
                    stroke={EVIDENCE_COLORS[index % EVIDENCE_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      )}
    </Card>
  );
};

export default DynamicTelemetryChart;
