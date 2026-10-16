import type { CollectionPolicy } from "@/types/collection";
import type { ExplorerNode, NavigationIndex } from "../explorer/navigationIndex";
import type { SystemDocument, SystemRuntime } from "./systemTypes";

import type { RuleScope } from "./collectionRuleTypes";
export type { RuleScope, CollectionRule, RuleEdit, RuleChange, PolicyOrigin } from "./collectionRuleTypes";
export const scopeKey = (scope: RuleScope) => JSON.stringify([scope.kind, scope.connection_id, scope.topic_prefix ?? null, scope.reading_id ?? null]);
export const policyLabel = (policy?: CollectionPolicy) => !policy || policy.mode === "off" ? "Off" : policy.mode === "original" ? "Original rate" : `Sample · ${policy.interval_seconds}s`;

export function scopeForNode(node?: ExplorerNode): RuleScope | undefined {
  if (!node?.connectionId) return;
  if (node.entityKind === "stream") return { kind: "reading", connection_id: node.connectionId, reading_id: node.objectId };
  if (node.kind === "connection") return { kind: "broker", connection_id: node.connectionId };
  if (node.kind === "topic") return { kind: "topic", connection_id: node.connectionId, topic_prefix: node.topic };
}

export function scopeReadingIds(index: NavigationIndex, node: ExplorerNode): string[] {
  if (node.kind !== "topic") return node.streamIds;
  const result = new Set<string>();
  const pending = [node.key];
  while (pending.length) {
    const next = index.nodes.get(pending.pop()!);
    if (!next) continue;
    next.streamIds.forEach(id => result.add(id));
    pending.push(...next.children);
  }
  return [...result];
}

/** Recording rules operate on MQTT scopes, including every entity on that broker. */
export function recordingScopeReadingIds(document: SystemDocument, node: ExplorerNode): string[] {
  const scope = scopeForNode(node);
  if (!scope) return [];
  return document.streams.filter(stream => stream.connection_id === scope.connection_id
    && (scope.kind === "broker" || scope.kind === "reading" && stream.id === scope.reading_id
      || scope.kind === "topic" && (stream.topic === scope.topic_prefix || stream.topic.startsWith((scope.topic_prefix ?? "") + "/"))))
    .map(stream => stream.id);
}

export function sourceHref(readingIds: string[], document?: SystemDocument, returnTo?: string) {
  const first = document?.streams.find(stream => readingIds.includes(stream.id));
  const query = new URLSearchParams();
  if (first) query.set("broker", first.connection_id);
  if (readingIds.length === 1) query.set("reading", readingIds[0]!);
  if (returnTo?.startsWith("/?")) query.set("returnTo", returnTo);
  return `/sources${query.size ? `?${query}` : ""}`;
}

export function originLabel(runtime: SystemRuntime | undefined, id: string, document: SystemDocument) {
  const origin = runtime?.bindings?.[id]?.policy_origin;
  if (origin?.needs_review) return "Needs review · not included";
  if (!origin?.scope) return "Default setting";
  if (!origin.inherited) return "Custom setting";
  const source = origin.scope.kind === "broker" ? document.connections.find(item => item.id === origin.scope?.connection_id)?.label : origin.scope.topic_prefix;
  return `Inherited from ${source ?? "parent"}`;
}

export function safeServiceReturn(value: string | null) {
  if (!value?.startsWith("/?")) return "/";
  const url = new URL(value, "https://local.invalid");
  const setup = url.searchParams.get("create") === "monitoring" || !!url.searchParams.get("pipeline");
  return url.origin === "https://local.invalid" && url.pathname === "/" && setup ? value : "/";
}
