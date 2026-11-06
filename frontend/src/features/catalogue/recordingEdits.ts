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

const broker = (broker_id: string): RuleScope => ({ kind: "broker", broker_id });
/** Record every message of a broker, including readings registered later. */
export const startRecording = (id: string): RuleEdit[] => [recordingEdit(broker(id), "original", 10)];
/** Stop every recording on a broker: its own rule and any topic or reading that records on its own. */
export function stopRecording(id: string, runtime?: SystemRuntime): RuleEdit[] {
  const exceptions = (runtime?.collection_rules ?? []).filter(rule => rule.scope.broker_id === id
    && rule.scope.kind !== "broker" && rule.policy && rule.policy.mode !== "off");
  return [{ scope: broker(id), operation: "inherit" }, ...exceptions.map(rule => ({ scope: rule.scope, operation: "inherit" as const }))];
}
