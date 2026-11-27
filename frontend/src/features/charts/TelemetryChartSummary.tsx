import { formatChartTime, formatNumber, type TelemetryChartModel } from "./telemetry-chart";
import { alarmText } from "./telemetry-detectors";

export function TelemetryChartSummary({ model, timeZone, showTelemetry = true, historical = false }: {
  model: TelemetryChartModel; timeZone: string; showTelemetry?: boolean; historical?: boolean;
}) {
  const latestTelemetry = model.telemetry.data[model.telemetry.data.length - 1];
  return (
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-border/60 pt-3 text-xs text-muted-foreground">
      {showTelemetry && latestTelemetry && (
        <span>
          {historical ? 'Latest in window · ' : 'Current '}{model.telemetry.name}: {formatNumber(latestTelemetry[1])}
          {model.telemetry.unit ? ` ${model.telemetry.unit}` : ""} at{" "}
          {formatChartTime(latestTelemetry[0], timeZone, "tooltip")}
        </span>
      )}
      {model.secondarySeries.map((series) => {
        const latest = series.latestObservation;
        // Only a score drawn against its threshold is named as a share of it, in the units of its axis.
        const ratio = series.relative && latest.value !== null && latest.threshold ? latest.value / latest.threshold : null;
        return (
          <span key={series.id}>
            {latest.isInfinite || (latest.value === null && latest.logValue !== null) ? (
              <>
                {series.name}: beyond numeric range{latest.logValue !== null ? ` (ln: ${formatNumber(latest.logValue)})` : ""}; alarm {alarmText(latest)}
              </>
            ) : ratio !== null ? <>{series.name}: now <strong className="font-medium text-foreground">{formatNumber(Number(ratio.toPrecision(2)))}× threshold</strong>
              {" "}(score {formatNumber(latest.value!)}, threshold {formatNumber(latest.threshold!)})</>
              : <>{series.name}: {latest.value !== null ? formatNumber(latest.value) : "unavailable"}
                {latest.threshold !== null ? ` · Threshold: ${formatNumber(latest.threshold)}` : ""}</>}
          </span>
        );
      })}
    </div>
  );
}
