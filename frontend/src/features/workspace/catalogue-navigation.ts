import { WORKSPACE_PATHS } from "./application-navigation";
import type { ExplorerNode, NavigationIndex } from "@/domain/system/navigationIndex";
import type { SystemDocument } from "@/types/system";

/** Use the visible signal name or full topic, rather than its last MQTT segment. */
export function catalogueSelectionLabel(document: SystemDocument, node?: ExplorerNode) {
  if (node?.entityKind === "stream") return document.readings.find(reading => reading.id === node.objectId)?.label ?? node.label;
  return node?.topic ?? node?.label;
}

export const isWorkspacePath = (path: string) => WORKSPACE_PATHS.includes(path);

/** Resolve old deep links and the shared selection against the same catalogue. */
export function catalogueSelection(index: NavigationIndex, params: URLSearchParams) {
  const key = params.get("source");
  if (key) return index.nodes.get(key);
  const reading = params.get("reading"), entity = params.get("entity"), broker = params.get("broker");
  const topic = params.get("topic");
  if (reading || entity) {
    const kind = reading ? "stream" : "device";
    const nodes = (index.objectKeys.get((reading ?? entity)!) ?? []).flatMap(id => index.nodes.get(id) ?? []);
    return nodes.find(node => node.entityKind === kind && (!broker || node.connectionId === broker));
  }
  if (broker) return [...index.nodes.values()].find(node => node.connectionId === broker
    && (topic !== null ? node.kind === "topic" && node.topic === topic : node.kind === "connection"));
}

export const hasCatalogueSelection = (params: URLSearchParams) =>
  ["source", "reading", "entity", "broker", "topic"].some(key => params.has(key));

export function withCatalogueSource(href: string, source?: ExplorerNode | string) {
  const url = new URL(href, "https://workspace.invalid");
  if (source) url.searchParams.set("source", typeof source === "string" ? source : source.key);
  else url.searchParams.delete("source");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function selectedSourceHref(path: string, node?: ExplorerNode | null) {
  return withCatalogueSource(path, node ?? undefined);
}
