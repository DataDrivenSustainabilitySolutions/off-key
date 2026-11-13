import type { TimeValue } from "./telemetry-data";
import type { TelemetryEventGroup } from "./telemetry-events";
import type { TelemetryHistory } from "@/types/telemetry-history";

/** Series shapes shared by the chart builder and its tooltip. */
export interface TelemetryChartSeries {
  id: string;
  name: string;
  unit?: string;
  color: string;
  data: TimeValue[];
  presentation?: TelemetryHistory;
}
export interface MonitoringChartReading extends TelemetryChartSeries {
  inputKey?: string;
  valueType?: "number" | "boolean";
  pendingTelemetry: TimeValue[];
  anomalyMarkers: TelemetryEventGroup[];
  /** Alarm episodes at this reading's input times: consecutive alarm results share one span. */
  alarmSpans?: Array<[startMs: number, endMs: number]>;
}
