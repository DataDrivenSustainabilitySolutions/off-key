import { formatNumber } from "./telemetry-chart";
import type { SecondaryChartSeries } from "./telemetry-detectors";

/** The latest result of a score in words: a share of its threshold only where the chart draws it that way. */
export function latestScoreText({ name, relative, latestObservation: latest }: Pick<SecondaryChartSeries, "name" | "relative" | "latestObservation">) {
  if (relative && latest.value !== null && latest.threshold) {
    return {
      headline: `${name}: now ${formatNumber(Number((latest.value / latest.threshold).toPrecision(2)))}× threshold`,
      detail: `Score ${formatNumber(latest.value)}, threshold ${formatNumber(latest.threshold)}`,
    };
  }
  const value = latest.value !== null ? formatNumber(latest.value) : latest.isInfinite ? "∞" : "unavailable";
  return {
    headline: `${name}: ${value}`,
    detail: `Score threshold: ${latest.threshold !== null ? formatNumber(latest.threshold) : "unavailable"}`,
  };
}
