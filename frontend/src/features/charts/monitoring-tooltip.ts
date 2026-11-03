import type { MonitoringChartReading } from "./types";
import type { DetectionObservation } from "./telemetry-detectors";

type Entry = { seriesId?: unknown; seriesName?: unknown; value?: unknown; data?: { observation?: DetectionObservation } };

/** Read the exact recorded inputs for a joint result, rather than nearby samples. */
export function formatMonitoringObservationTooltip(
  params: unknown,
  readings: readonly MonitoringChartReading[],
  formatTime: (time: number) => string,
  formatValue: (value: number) => string,
): string | undefined {
  const entries = (Array.isArray(params) ? params : [params]).filter(
    (value): value is Entry => typeof value === "object" && value !== null,
  );
  const evaluated = entries.filter(entry => entry.data?.observation?.inputTimestamps);
  const observation = evaluated[0]?.data?.observation;
  if (!observation?.inputTimestamps) return undefined;
  const anchor = entries.find(entry => Array.isArray(entry.value) && typeof entry.value[0] === "number");
  const anchorReading = readings.find(reading => anchor?.seriesId === reading.id || anchor?.seriesId === `pending-${reading.id}`)
    ?? readings.find(reading => reading.name === anchor?.seriesName);
  const anchorTime = Array.isArray(anchor?.value) ? Number(anchor.value[0]) : undefined;
  if (anchorReading?.inputKey && anchorTime !== undefined
    && Date.parse(observation.inputTimestamps[anchorReading.inputKey] ?? "") !== anchorTime) {
    const point = anchorReading.data.find(([time]) => time === anchorTime);
    return [formatTime(anchorTime), `${anchorReading.name}: ${point ? `${formatValue(point[1])}${anchorReading.unit ? ` ${anchorReading.unit}` : ""}` : "unavailable"}`,
      "No evaluated result for this input sample."].join("\n");
  }
  const lines = [formatTime(observation.timeMs)];
  for (const reading of readings) {
    const timestamp = reading.inputKey ? observation.inputTimestamps[reading.inputKey] : undefined;
    const inputTime = timestamp ? Date.parse(timestamp) : undefined;
    const point = inputTime === undefined ? undefined : reading.data.find(([time]) => time === inputTime);
    lines.push(`${reading.name}: ${point ? `${formatValue(point[1])}${reading.unit ? ` ${reading.unit}` : ""}` : "input not loaded"}`);
    if (inputTime !== undefined && inputTime !== observation.timeMs) lines.push(`  Input time: ${formatTime(inputTime)} (${inputTime - observation.timeMs} ms)`);
  }
  // The features the detector scored at this observation, such as phase deviations.
  for (const entry of entries) {
    if (typeof entry.seriesId !== "string" || !entry.seriesId.startsWith("input:") || !Array.isArray(entry.value)) continue;
    const [time, value] = entry.value as unknown[];
    if (time !== observation.timeMs || typeof value !== "number") continue;
    lines.push(`${String(entry.seriesName)}: ${formatValue(value)}`);
  }
  for (const entry of evaluated) {
    const result = entry.data!.observation!;
    if (result.timeMs !== observation.timeMs) continue;
    lines.push(`${String(entry.seriesName)}: ${result.value === null ? result.isInfinite ? "∞" : "unavailable" : String(result.value)}`);
    lines.push(`Alarm threshold: ${result.threshold === null ? "unavailable" : String(result.threshold)}`);
    lines.push(`Alarm: ${result.alarmActive ? "active" : "inactive"}`);
  }
  // A policy that combines detectors names each one's part, so an alarm names its detector.
  for (const detector of observation.detectors ?? []) {
    const surprise = detector.surprise === null ? "unavailable" : String(Number(detector.surprise.toPrecision(4)));
    const score = detector.score === null ? "unavailable" : formatValue(detector.score);
    lines.push(`Detector ${detector.detector_id}: surprise ${surprise}, score ${score}`);
  }
  const count = Object.keys(observation.inputTimestamps).length;
  if (count > 1) lines.push(`Joint result across ${count} inputs; no per-sensor attribution.`);
  return lines.join("\n");
}
