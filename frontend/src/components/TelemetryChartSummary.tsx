import { formatChartTime, formatNumber, type TelemetryChartModel } from "@/lib/telemetry-chart";

export function TelemetryChartSummary({ model, timeZone }: { model: TelemetryChartModel; timeZone: string }) {
  const latestTelemetry = model.telemetry.data[model.telemetry.data.length - 1];
  return (
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-border/60 pt-3 text-xs text-muted-foreground">
      {latestTelemetry && (
        <span>
          Current {model.telemetry.name}: {latestTelemetry[1]}
          {model.telemetry.unit ? ` ${model.telemetry.unit}` : ""} at{" "}
          {formatChartTime(latestTelemetry[0], timeZone, "tooltip")}
        </span>
      )}
      {model.secondarySeries.map((series) => {
        const latest = series.latestObservation;
        if (!latest) return null;
        return (
          <span key={series.id}>
            {series.name}: {latest.isInfinite || (latest.value === null && latest.logValue !== null) ? (
              <>
                Beyond numeric range{latest.logValue !== null ? ` (ln: ${formatNumber(latest.logValue)})` : ""}; {latest.alarmActive ? "alarm active" : "alarm inactive"}
              </>
            ) : latest.value !== null ? formatNumber(latest.value) : "Unavailable"}
            {latest.threshold !== null ? ` · Threshold: ${formatNumber(latest.threshold)}` : ""}
          </span>
        );
      })}
    </div>
  );
}
