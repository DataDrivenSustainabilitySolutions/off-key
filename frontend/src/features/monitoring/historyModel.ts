import type { TelemetryDataPoint } from "@/types/charger";
import type { MonitoringChartEvidence } from "@/types/monitoring";
import type { MonitoringChartModel } from "@/lib/telemetry-chart";
import { normalizeTelemetry } from "@/lib/telemetry-data";
import { buildSelectedDetectorSeries, collectMonitoringChartDetectors, type SelectedDetectorIds } from "@/lib/telemetry-detectors";
import type { MonitoringInput } from "./serviceModel";

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
  const rows = evidence.filter(item => item.service_id === serviceId);
  const detectors = collectMonitoringChartDetectors(rows).map(detector => ({ ...detector,
    name: detector.pane === "adaptive" && allInputs.length > 1 ? "Joint anomaly score" : detector.name,
  }));
  const times = [...new Set(detectors.flatMap(detector => detector.observations.map(observation => observation.timeMs)))].sort((a, b) => a - b);
  const secondarySeries = buildSelectedDetectorSeries({ detectors, telemetryTimes: times, selectedDetectorIds });
  const readings = inputs.map(input => {
    const { stream, binding } = input;
    const data = normalizeTelemetry(histories.get(stream.id) ?? []);
    const scoredTimes = rows.flatMap(row => {
      const time = Date.parse(row.input_timestamps[binding.telemetry_key] ?? "");
      return Number.isFinite(time) ? [time] : [];
    });
    const lastScore = scoredTimes.length ? Math.max(...scoredTimes) : undefined;
    const index = allInputs.findIndex(item => item.stream.id === stream.id);
    const palette = dark ? DARK_READING_COLORS : READING_COLORS;
    const duplicate = inputs.some(other => other.stream.id !== stream.id && other.stream.label === stream.label);
    return { id: `reading:${stream.id}`, inputKey: binding.telemetry_key,
      name: duplicate ? `${input.path} / ${stream.label}` : stream.label,
      unit: stream.unit, color: palette[index % palette.length]!, data,
      pendingTelemetry: !operational || lastScore === undefined ? [] : data.filter(([time]) => time > lastScore),
      anomalyMarkers: [],
      alarmTimes: [...new Set(rows.filter(row => row.alarm).flatMap(row => {
        const time = Date.parse(row.input_timestamps[binding.telemetry_key] ?? "");
        return Number.isFinite(time) ? [time] : [];
      }))],
    };
  });
  const allTimes = [...times, ...readings.flatMap(reading => reading.data.map(([time]) => time))];
  const model: MonitoringChartModel = { readings, secondarySeries, range: {},
    extent: allTimes.length ? [Math.min(...allTimes), Math.max(...allTimes)] : undefined };
  return { model, detectors };
}
