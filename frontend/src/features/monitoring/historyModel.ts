import { epochMilliseconds } from "@/lib/timestamps";
import type { TelemetryDataPoint } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import type { MonitoringChartModel } from "@/features/charts/telemetry-chart";
import { normalizeTelemetry } from "@/features/charts/telemetry-data";
import { buildDetectorInputSeries } from "@/features/charts/detector-inputs";
import { buildSelectedDetectorSeries, collectMonitoringChartDetectors, type SelectedDetectorIds } from "@/features/charts/telemetry-detectors";
import type { MonitoringInput } from "@/domain/monitoring/serviceModel";

export const MAX_VISIBLE_READINGS = 6;
const READING_COLORS = ["#3a7e72", "#7161b5", "#b36b32", "#3d7fa5", "#a75679", "#6f8434"];
const DARK_READING_COLORS = ["#89bdaf", "#b6a2ed", "#e5ac73", "#80bce0", "#e5a0bf", "#becf88"];

export function buildServiceHistoryModel({
  serviceId, inputs, allInputs, histories, evidence, dark, selectedDetectorIds, operational = true,
}: {
  serviceId: string;
  inputs: MonitoringInput[];
  allInputs: MonitoringInput[];
  histories: ReadonlyMap<string, readonly TelemetryDataPoint[]>;
  evidence: readonly MonitoringChartEvidence[];
  dark: boolean;
  selectedDetectorIds?: SelectedDetectorIds;
  operational?: boolean;
}) {
  const rows = evidence.filter(item => item.monitor_id === serviceId);
  const detectors = collectMonitoringChartDetectors(rows).map(detector => ({ ...detector,
    name: detector.pane === "adaptive" && allInputs.length > 1 ? "Joint anomaly score" : detector.name,
  }));
  const times = [...new Set(detectors.flatMap(detector => detector.observations.map(observation => observation.timeMs)))].sort((a, b) => a - b);
  const secondarySeries = buildSelectedDetectorSeries({ detectors, telemetryTimes: times, selectedDetectorIds });
  const palette = dark ? DARK_READING_COLORS : READING_COLORS;
  const readings = inputs.map(input => {
    const { stream } = input;
    const data = normalizeTelemetry(histories.get(stream.id) ?? []);
    // One parse per evidence row yields both the latest scored time and the alarm episodes:
    // results in a row that all alarm are one episode, ended by the next quiet result.
    const scored = rows.flatMap(row => {
      const time = epochMilliseconds(row.input_timestamps[stream.id] ?? "");
      return Number.isFinite(time) ? [{ time, alarm: row.alarm }] : [];
    }).sort((left, right) => left.time - right.time);
    const lastScore = scored[scored.length - 1]?.time;
    const alarmSpans: Array<[number, number]> = [];
    let open: [number, number] | undefined;
    for (const { time, alarm } of scored) {
      if (!alarm) open = undefined;
      else if (open) open[1] = time;
      else alarmSpans.push(open = [time, time]);
    }
    const index = allInputs.findIndex(item => item.stream.id === stream.id);
    const duplicate = inputs.some(other => other.stream.id !== stream.id && other.stream.label === stream.label);
    return { id: `reading:${stream.id}`, inputKey: stream.id,
      name: duplicate ? `${input.path} / ${stream.label}` : stream.label,
      unit: stream.unit, color: palette[index % palette.length]!, data,
      pendingTelemetry: !operational || lastScore === undefined ? [] : data.filter(([time]) => time > lastScore),
      anomalyMarkers: [],
      alarmSpans,
    };
  });
  // Detector times and normalized telemetry are sorted, so their ends bound the extent
  // without spreading every point into Math.min/Math.max.
  let first = times[0], last = times[times.length - 1];
  for (const { data } of readings) {
    const start = data[0]?.[0], end = data[data.length - 1]?.[0];
    if (start !== undefined && (first === undefined || start < first)) first = start;
    if (end !== undefined && (last === undefined || end > last)) last = end;
  }
  const detectorInputs = buildDetectorInputSeries(rows, row => epochMilliseconds(row.timestamp));
  const model: MonitoringChartModel = { readings, detectorInputs, secondarySeries, range: {},
    extent: first === undefined || last === undefined ? undefined : [first, last] };
  return { model, detectors };
}
