import type { CollectionPolicy } from "../../types/collection";

export type RuleScope = { kind: "broker" | "topic" | "reading"; connection_id: string; topic_prefix?: string | null; reading_id?: string | null };
export type CollectionRule = { scope: RuleScope; policy: CollectionPolicy | null; include_future_readings: boolean; admitted_before: number };
export type RuleEdit = { scope: RuleScope; operation: "set" | "inherit" | "include" | "restore"; policy?: CollectionPolicy; include_future_readings?: boolean; restore_rule?: CollectionRule | null };
export type RuleChange = { expected_revision: number; expected_collection_revision: number; rule_changes: RuleEdit[]; pause_affected_monitors?: boolean };
export type PolicyOrigin = { scope: RuleScope | null; inherited: boolean; needs_review: boolean };
