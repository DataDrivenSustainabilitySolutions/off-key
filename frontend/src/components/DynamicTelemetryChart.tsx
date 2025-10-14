import React, { useMemo, useState } from 'react';
import { Card, CardContent, CardTitle } from '@/components/ui/card';
import DateTimePicker from '@/components/DateTimePicker';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  ReferenceArea,
  Tooltip,
} from 'recharts';
import { TelemetryTypeData } from '@/dataFetch/FetchContext';
import { createAnomalyZones, filterAnomalies, hasAnomaly, getAnomalyStyle, createAnomalyTooltip } from '@/lib/anomaly-utils';
import { isWithinTimeRange } from '@/lib/time-utils';
import { NoChartsAvailable } from '@/components/LoadingStates';

interface DynamicTelemetryChartProps {
  telemetryData: TelemetryTypeData;
  chargerId: string;
  anomalies?: any[]; // Import proper type from anomaly-utils
}

export const DynamicTelemetryChart: React.FC<DynamicTelemetryChartProps> = ({
  telemetryData,
  anomalies = []
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
    switch (category) {
      case 'cpu': return '#8884d8';
      case 'system': return '#82ca9d';
      case 'controller': return '#ffc658';
      case 'other': return '#ff7300';
      default: return '#8884d8';
    }
  };

  // Format timestamp for display
  const formatDateMultiline = (value: string) => {
    const date = new Date(value);
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    const second = String(date.getSeconds()).padStart(2, '0');
    return `${day}.${month}, ${hour}:${minute}:${second}`;
  };

  // Helper function for quick time filters
  const handleLastMinutes = (minutes: number) => {
    if (telemetryData.data.length === 0) return;
    const times = telemetryData.data.map(d => new Date(d.timestamp).getTime());
    const maxTime = Math.max(...times);
    const minTime = maxTime - minutes * 60 * 1000;
    setFromDate(new Date(minTime));
    setToDate(new Date(maxTime));
  };

  const last30Min = () => handleLastMinutes(30);
  const lastHour = () => handleLastMinutes(60);

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
    createAnomalyZones(telemetryAnomalies, filteredData),
    [telemetryAnomalies, filteredData]
  );

  if (filteredData.length === 0) {
    return (
      <Card className="w-full transition-all duration-300 overflow-hidden">
        <div className="flex justify-between p-4">
          <CardTitle>{displayName}</CardTitle>
          <span className="text-xs text-muted-foreground capitalize">
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
    <Card className={`w-full transition-all duration-300 overflow-hidden ${collapsed ? 'h-16' : 'h-96'}`}>
      <div className="flex justify-between items-center p-4">
        <div className="flex items-center gap-4">
          <CardTitle>{displayName}</CardTitle>
          <span className="text-xs text-muted-foreground capitalize px-2 py-1 bg-muted rounded">
            {telemetryData.category}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!collapsed && (
            <>
              <DateTimePicker
                value={fromDate}
                onChange={setFromDate}
                placeholder="From"
                className="w-40 h-8 text-xs"
              />
              <DateTimePicker
                value={toDate}
                onChange={setToDate}
                placeholder="To"
                className="w-40 h-8 text-xs"
              />
              <div className="flex items-center h-8 ml-2 space-x-2 rounded-lg border bg-white px-2 dark:bg-transparent">
                <button
                  onClick={last30Min}
                  className="text-xs text-gray-700 hover:underline focus:outline-none dark:text-white cursor-pointer whitespace-nowrap"
                >
                  last 30 Minutes
                </button>
                <div className="h-4 border-l border-gray-300" />
                <button
                  onClick={lastHour}
                  className="text-xs text-gray-700 hover:underline focus:outline-none dark:text-white cursor-pointer whitespace-nowrap"
                >
                  last Hour
                </button>
              </div>
            </>
          )}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            onClick={() => setCollapsed(!collapsed)}
            className={`size-6 cursor-pointer transition-transform ${collapsed ? 'rotate-180' : ''}`}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="m19.5 8.25-7.5 7.5-7.5-7.5"
            />
          </svg>
        </div>
      </div>

      {!collapsed && (
        <CardContent className="pt-0">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={filteredData.slice().reverse()}
              margin={{
                top: 5,
                right: 30,
                left: 20,
                bottom: 5,
              }}
            >
              <CartesianGrid strokeDasharray="5 5" />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatDateMultiline}
              />
              <YAxis dataKey="value" />
              <Tooltip />
              <Legend />
              
              {/* Render anomaly zones */}
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
                type="monotone"
                dataKey="value"
                stroke={getCategoryColor(telemetryData.category)}
                activeDot={false}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;
                  const anomaly = hasAnomaly(payload?.timestamp, telemetryAnomalies);
                  if (anomaly && cx !== undefined && cy !== undefined) {
                    const style = getAnomalyStyle(anomaly.anomaly_type);
                    return (
                      <g key={`anomaly-${payload.timestamp}`}>
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
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      )}
    </Card>
  );
};

export default DynamicTelemetryChart;