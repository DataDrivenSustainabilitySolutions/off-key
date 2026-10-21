import { useSyncExternalStore } from "react";
import { Plug, Square } from "lucide-react";
import type { SystemLiveTelemetry } from "./systemLiveTelemetry";

type Props = {
  telemetry: SystemLiveTelemetry;
  canStart: boolean;
  canView: boolean;
  disabled: boolean;
};
const titles = {
  idle: "Live view off",
  connecting: "Connecting",
  live: "Live",
  waiting: "Waiting",
  reconnecting: "Reconnecting",
  blocked: "Unavailable",
  error: "Unavailable",
  paused: "Paused",
};
export function SystemLiveControls({
  telemetry,
  canStart,
  canView,
  disabled,
}: Props) {
  const status = useSyncExternalStore(
    telemetry.subscribeUpdates,
    telemetry.getStatus,
  );
  const issues = status.connections.filter((connection) =>
    ["blocked", "error", "reconnecting"].includes(connection.state),
  ).length;
  return (
    <div className="sp-system-live-controls">
      <div className="sp-live-indicator" title={status.message} role="status">
        <i className={status.phase === "live" ? "active" : ""} />
        {titles[status.phase]}
        {status.phase === "live" && issues > 0 && (
          <span> · {issues} connection issues</span>
        )}
      </div>
      {status.dataSource === "simulated" && status.active && (
        <span className="sp-live-source">Simulated data</span>
      )}
      {status.active || status.phase === "paused" ? (
        <button className="sp-live-toggle" title="Disconnect this view." onClick={() => telemetry.stop()}>
          <Square size={11} />
          Disconnect
        </button>
      ) : (
        <button
          className="sp-live-toggle"
          disabled={disabled || !canView}
          onClick={() => void telemetry.start()}
          title={
            canView
              ? canStart ? "Connect to configured brokers." : "View the active live connection."
              : "Sign in to view live data."
          }
        >
          <Plug size={13} />
          {status.phase === "error" || status.phase === "blocked"
            ? "Retry"
            : "Connect"}
        </button>
      )}
      {(status.phase === "error" ||
        status.phase === "blocked" ||
        status.phase === "waiting") && (
        <p className="sp-live-message">{status.message}</p>
      )}
    </div>
  );
}
