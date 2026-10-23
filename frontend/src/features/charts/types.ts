import type { TimeValue } from "./telemetry-data";
import type { TelemetryEventGroup } from "./telemetry-events";

/** Series shapes shared by the chart builder and its tooltip. */
export interface TelemetryChartSeries {
  id: string;
  name: string;
  unit?: string;
  color: string;
  data: TimeValue[];
}
export interface MonitoringChartReading extends TelemetryChartSeries {
  inputKey?: string;
  valueType?: "number" | "boolean";
  pendingTelemetry: TimeValue[];
  anomalyMarkers: TelemetryEventGroup[];
  alarmTimes?: number[];
}
