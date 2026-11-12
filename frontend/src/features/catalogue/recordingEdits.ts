import type { RuleEdit, RuleScope } from "@/domain/system/collectionRules";
import type { CollectionPolicy } from "@/types/collection";
import type { SystemRuntime } from "@/types/system";

export type Choice = "inherit" | CollectionPolicy["mode"];

/** The edit that makes a scope record the way it was chosen; brokers and topics also take readings added later. */
export function recordingEdit(scope: RuleScope, choice: Choice, interval: number): RuleEdit {
  // A broker that is off has no rule of its own, so its readings fall back to the default (off).
  if (choice === "inherit" || choice === "off" && scope.kind === "broker") return { scope, operation: "inherit" };
  return { scope, operation: "set", policy: { mode: choice, interval_seconds: interval },
    ...scope.kind === "reading" ? {} : { include_future_readings: true } };
}

/** How often an HTTP source is asked until someone chooses an interval, in seconds. */
export const POLL_SECONDS = 60;
const broker = (broker_id: string): RuleScope => ({ kind: "broker", broker_id });
/** Record a broker, including readings registered later: every message it sends, or an HTTP source at intervals. */
export const startRecording = (id: string, polled = false): RuleEdit[] =>
  [recordingEdit(broker(id), polled ? "sample" : "original", polled ? POLL_SECONDS : 10)];
/** Stop every recording on a broker: its own rule and any topic or reading that records on its own. */
export function stopRecording(id: string, runtime?: SystemRuntime): RuleEdit[] {
  const exceptions = (runtime?.collection_rules ?? []).filter(rule => rule.scope.broker_id === id
    && rule.scope.kind !== "broker" && rule.policy && rule.policy.mode !== "off");
  return [{ scope: broker(id), operation: "inherit" }, ...exceptions.map(rule => ({ scope: rule.scope, operation: "inherit" as const }))];
}
