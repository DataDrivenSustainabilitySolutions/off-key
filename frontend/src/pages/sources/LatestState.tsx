import { useEffect, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";

const endpoint = "/v1/sources";
type SensorState = {
  sensor_key: string;
  value: unknown;
  received_at: string;
  is_snapshot: boolean;
};

export function LatestState({ chargerId }: { chargerId: string }) {
  const [states, setStates] = useState<SensorState[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () =>
      apiUtils
        .get<SensorState[]>(`${endpoint}/state/${chargerId}`)
        .then((data) => {
          if (active) {
            setStates(data);
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(getErrorMessage(e));
        });
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [chargerId]);
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-3">
      {error && <p role="alert">{error}</p>}
      {!error && states.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No observations collected yet.
        </p>
      )}
      {states.map((state) => (
        <div
          key={state.sensor_key}
          className="rounded-lg bg-muted/50 p-3 text-xs"
        >
          <p className="break-all font-medium">
            {state.sensor_key}: {String(state.value)}
          </p>
          <p className="mt-1 text-muted-foreground">
            {state.is_snapshot
              ? "Snapshot · measurement age unknown"
              : "Observed"}{" "}
            · {new Date(state.received_at).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
