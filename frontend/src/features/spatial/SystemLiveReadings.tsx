import { useEffect, useState, useSyncExternalStore } from "react";
import { EChart } from "@/components/EChart";
import type { TelemetryChartOption } from "@/lib/telemetry-chart";
import type { SpatialNode } from "./types";
import type { SystemLiveTelemetry } from "./systemLiveTelemetry";

const number = (value: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
const time = (value: number) =>
  new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(value);
const phases = {
  idle: "Disconnected",
  connecting: "Connecting",
  live: "Connected",
  waiting: "Waiting",
  reconnecting: "Reconnecting",
  blocked: "Unavailable",
  error: "Unavailable",
  paused: "Paused",
};

type Props = {
  node: SpatialNode;
  telemetry: SystemLiveTelemetry;
  color?: string;
};
export function SystemLiveReadings({
  node,
  telemetry,
  color = "#397f74",
}: Props) {
  const status = useSyncExternalStore(
    telemetry.subscribeUpdates,
    telemetry.getStatus,
  );
  const [now, setNow] = useState(Date.now);
  const [minutes, setMinutes] = useState(15);
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);
  const snapshot = telemetry.getSnapshot(node.id);
  const connectionId =
    node.system?.kind === "connection" ? node.id : node.system?.connectionId;
  const connection = status.connections.find(
    (entry) => entry.connection_id === connectionId,
  );
  const showChart =
    node.system?.kind === "stream" &&
    ["number", "boolean"].includes(node.system.valueType ?? "");
  const samples = snapshot?.samples;
  const cutoff = now - minutes * 60000;
  const data = (samples ?? [])
    .filter((sample) => sample.timestamp >= cutoff)
    .map((sample) => [sample.timestamp, sample.value]);
  const isBoolean = node.system?.valueType === "boolean";
  const option: TelemetryChartOption = {
    backgroundColor: "#fff",
    animation: false,
    grid: { left: 42, right: 12, top: 16, bottom: 32 },
    tooltip: { trigger: "axis", confine: true },
    xAxis: {
      type: "time",
      min: cutoff,
      max: now,
      splitNumber: 3,
      axisLabel: { fontSize: 10, color: "#83928b" },
      axisLine: { lineStyle: { color: "#e1e8e4" } },
    },
    yAxis: {
      type: "value",
      scale: !isBoolean,
      ...(isBoolean ? { min: 0, max: 1, interval: 1 } : {}),
      splitNumber: 3,
      axisLabel: { fontSize: 10, color: "#83928b" },
      splitLine: { lineStyle: { color: "#f1f4f2" } },
    },
    series: [
      {
        type: "line",
        name: node.label,
        data,
        showSymbol: data.length < 2,
        symbolSize: 4,
        ...(isBoolean ? { step: "end" } : {}),
        connectNulls: false,
        sampling: "lttb",
        lineStyle: { width: 2, color },
        areaStyle: { color, opacity: 0.045 },
      },
    ],
  };
  const age = snapshot?.lastSeen
    ? Math.max(0, Math.floor((now - snapshot.lastSeen) / 1000))
    : null;
  const live = status.phase !== "idle";
  const rateUnit = node.system?.kind === "device" ? "readings/s" : "msg/s";
  const reading = snapshot?.isAggregate
    ? number(snapshot.rate)
    : snapshot?.latestValue == null
      ? "—"
      : typeof snapshot.latestValue === "number"
        ? number(snapshot.latestValue)
        : String(snapshot.latestValue);
  const label = !live
    ? "Disconnected"
    : connection?.state === "connected"
      ? "Connected"
      : connection?.state
        ? connection.state[0]!.toUpperCase() + connection.state.slice(1)
        : phases[status.phase];
  return (
    <>
      <div className="sp-system-state" role="status">
        <i className={connection?.state === "connected" ? "active" : ""} />
        {label}
        <span>
          {!live ? "No live connection" : status.dataSource === "simulated"
            ? "Simulated data · memory only" : "Live data · memory only"}
        </span>
      </div>
      {live && (
        <section className="sp-system-readings" aria-label="Live telemetry">
          {!!connection?.message &&
            ["blocked", "error", "reconnecting"].includes(connection.state) && (
              <p className="sp-live-problem">{connection.message}</p>
            )}
          {status.phase === "error" && (
            <p className="sp-live-problem">{status.message}</p>
          )}
          <div className="sp-reading">
            <div>
              <span className="sp-overline">
                {snapshot?.isAggregate ? "Arrival rate" : "Latest value"}
              </span>
              <p
                className={
                  typeof snapshot?.latestValue === "string"
                    ? "sp-live-text-value"
                    : ""
                }
              >
                {reading}
                <span>{snapshot?.isAggregate ? rateUnit : node.unit}</span>
              </p>
            </div>
            <span className="sp-freshness">
              <i className={age !== null && age < 10 ? "active" : ""} />
              {snapshot?.retained
                ? "Retained value"
                : age === null
                  ? "Waiting for data"
                  : age === 0
                    ? "Just received"
                    : `${age}s ago`}
            </span>
          </div>
          <div className="sp-inspector-metrics">
            <div>
              <span>
                {node.system?.kind === "device"
                  ? "Stream arrivals"
                  : "Fresh arrivals"}
              </span>
              <strong>{number(snapshot?.received ?? 0)}</strong>
            </div>
            <div>
              <span>Arrival rate</span>
              <strong>
                {number(snapshot?.rate ?? 0)}
                <small> {rateUnit}</small>
              </strong>
            </div>
          </div>
          <dl className="sp-live-details">
            <dt>Last fresh receipt</dt>
            <dd>{snapshot?.lastSeen ? time(snapshot.lastSeen) : "—"}</dd>
            {!!snapshot?.retainedCount && (
              <>
                <dt>Retained deliveries</dt>
                <dd>{number(snapshot.retainedCount)}</dd>
              </>
            )}
            {!!snapshot?.decodeErrors && (
              <>
                <dt>Unreadable values</dt>
                <dd>{number(snapshot.decodeErrors)}</dd>
              </>
            )}
          </dl>
          {showChart && (
            <section className="sp-chart-section">
              <div className="sp-live-chart-heading">
                <h3>{isBoolean ? "State" : "Live history"}</h3>
                <select
                  aria-label="Live chart time range"
                  value={minutes}
                  onChange={(event) => setMinutes(Number(event.target.value))}
                >
                  <option value={5}>5 min</option>
                  <option value={15}>15 min</option>
                  <option value={60}>1 hour</option>
                  <option value={120}>2 hours</option>
                </select>
              </div>
              {data.length ? (
                <EChart
                  option={option}
                  resolvedTheme="light"
                  accessibleDescription={`Live ${node.label}. ${data.length} received samples in the last ${minutes} minutes.`}
                  className="sp-live-chart"
                />
              ) : (
                <div className="sp-live-chart-empty">
                  Waiting for the first value.
                </div>
              )}
              <p className="sp-chart-hint">
                {data.length} samples · at most one per second. Retained values
                are initial readings, not fresh traffic.
              </p>
            </section>
          )}
          <p className="sp-live-retention-note">
            Live data stays in memory for up to 2 hours, within a shared
            8,192 point limit. Disconnecting or changing the saved system clears
            it. No database history is written. Pulses sample fresh arrivals;
            counters include every delivery.
          </p>
        </section>
      )}
    </>
  );
}
