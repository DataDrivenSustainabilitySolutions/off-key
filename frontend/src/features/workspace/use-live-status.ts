import { useSyncExternalStore } from "react";
import type { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { LiveStatus } from "@/types/system-live";

const subscribeNothing = () => () => {};
const noStatus = () => undefined;

/** The live telemetry status, re-read on each update only while `subscribed`. */
export function useLiveStatus(telemetry: SystemLiveTelemetry, subscribed?: boolean): LiveStatus;
export function useLiveStatus(telemetry: SystemLiveTelemetry | undefined, subscribed?: boolean): LiveStatus | undefined;
export function useLiveStatus(telemetry: SystemLiveTelemetry | undefined, subscribed = true) {
  return useSyncExternalStore(telemetry && subscribed ? telemetry.subscribeUpdates : subscribeNothing, telemetry?.getStatus ?? noStatus);
}
