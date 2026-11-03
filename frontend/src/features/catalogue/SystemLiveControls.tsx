import { useSyncExternalStore } from "react";
import { Plug, Square } from "lucide-react";
import type { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";

type Props = {
  telemetry: SystemLiveTelemetry;
  canStart: boolean;
  canView: boolean;
  disabled: boolean;
  /** Sources offers the live view as a preview of a broker that is not recorded. */
  preview?: boolean;
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
  preview = false,
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
      {!(preview && status.phase === "idle") && <div className="sp-live-indicator" title={status.message} role="status">
        <i className={status.phase === "live" ? "active" : ""} />
        {preview && status.phase === "live" ? "Live preview" : titles[status.phase]}
        {status.phase === "live" && issues > 0 && (
          <span> · {issues} connection issues</span>
        )}
      </div>}
      {status.dataSource === "simulated" && status.active && (
        <span className="sp-live-source">Simulated data</span>
      )}
      {status.active || status.phase === "paused" ? (
        <button className="sp-live-toggle" title="Disconnect this view." onClick={() => telemetry.stop()}>
          <Square size={11} />
          Stop live view
        </button>
      ) : (
        <button
          className="sp-live-toggle"
          disabled={disabled || !canView}
          onClick={() => void telemetry.start()}
          title={
            canView
              ? preview ? "Stream the readings that are not recorded into this page while it is open."
                : canStart ? "Connect to configured brokers." : "View the active live connection."
              : "Sign in to view live data."
          }
        >
          <Plug size={13} />
          {status.phase === "error" || status.phase === "blocked"
            ? "Retry"
            : "View live"}
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
