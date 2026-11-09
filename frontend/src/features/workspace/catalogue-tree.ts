import { navigationRows, navigationTrail, searchNavigation, type ExplorerNode, type NavigationIndex } from "@/domain/system/navigationIndex";
import type { SystemGroup, SystemStream } from "@/types/system";

/** One visible line of the sidebar catalogue: a tree row, or a flattened search result. */
export type CatalogueRow = {
  node: ExplorerNode;
  /** A topic chain without branches reads as one row, such as "site/room". */
  label: string;
  depth: number;
  expandable: boolean;
  expanded: boolean;
  /** The unit of a reading, or the location of a search result. */
  detail?: string;
  /** Every ancestor and the node itself, for the row's full name. */
  path: string;
  color?: string;
};

type Streams = ReadonlyMap<string, SystemStream>;

/** A reading shows its display name; the topic segment is part of its path. */
const rowLabel = (node: ExplorerNode, label: string, streams: Streams) =>
  node.entityKind === "stream" ? streams.get(node.objectId ?? "")?.label ?? label : label;

/** Brokers and devices by name, then the full MQTT address. */
export function catalogueLocation(index: NavigationIndex, node: ExplorerNode) {
  const owners = navigationTrail(index, node.key).filter(ancestor => ancestor.kind === "connection" || ancestor.kind === "device"
    || ancestor.kind === "unassigned").filter(ancestor => ancestor.key !== node.key).map(ancestor => ancestor.label);
  return [...owners, ...(node.topic && node.kind !== "connection" && node.kind !== "device" ? [node.topic] : [])].join(" / ");
}

function fullPath(index: NavigationIndex, node: ExplorerNode, label: string) {
  const location = catalogueLocation(index, node);
  return location && location !== label ? `${label} — ${location}` : label;
}

/**
 * The visible rows of the catalogue tree: `roots`, and the children of every
 * expanded node beneath them. Collapsed branches cost nothing, so a catalogue of
 * any size renders only what its open branches show.
 */
export function catalogueTreeRows(index: NavigationIndex, roots: Array<{ node: ExplorerNode; label: string; color?: string }>,
  expanded: ReadonlySet<string>, streams: Streams): CatalogueRow[] {
  const rows: CatalogueRow[] = [];
  const stack = roots.map(root => ({ ...root, depth: 0 })).reverse();
  while (stack.length) {
    const { node, label: chainLabel, depth, color } = stack.pop()!;
    const label = rowLabel(node, chainLabel, streams);
    const expandable = node.children.length > 0;
    const open = expandable && expanded.has(node.key);
    const stream = node.entityKind === "stream" ? streams.get(node.objectId ?? "") : undefined;
    rows.push({ node, label, depth, expandable, expanded: open, color, detail: stream?.unit || undefined, path: fullPath(index, node, label) });
    if (!open) continue;
    const children = navigationRows(index, node.key);
    for (let position = children.length - 1; position >= 0; position -= 1) {
      stack.push({ node: children[position]!.node, label: children[position]!.label, depth: depth + 1, color: undefined });
    }
  }
  return rows;
}

/** Top-level rows: every broker, or the members of the chosen collection. */
export function catalogueRoots(index: NavigationIndex, collection?: SystemGroup) {
  if (!collection) return navigationRows(index, index.rootKey).map(({ node, label }) => ({ node, label }));
  return collection.member_ids.flatMap(id => {
    const node = index.nodes.get(index.objectKeys.get(id)?.[0] ?? "");
    return node ? [{ node, label: node.label, color: collection.color }] : [];
  });
}

/** Where a search result sits: its MQTT address first, then the device or broker that owns it. */
function searchContext(index: NavigationIndex, node: ExplorerNode) {
  const owner = navigationTrail(index, node.key).slice(0, -1).reverse()
    .find(ancestor => ancestor.kind === "device" || ancestor.kind === "connection" || ancestor.kind === "unassigned");
  const topic = node.kind === "connection" || node.kind === "device" ? undefined : node.topic;
  return [topic, owner?.label].filter(Boolean).join(" · ") || "Catalogue";
}

/** Search results flattened, each with where it sits in the catalogue. */
export function catalogueSearchRows(index: NavigationIndex, query: string, streams: Streams): CatalogueRow[] {
  return searchNavigation(index, query).map(node => {
    const label = rowLabel(node, node.label, streams);
    return { node, label, depth: 0, expandable: false, expanded: false,
      detail: searchContext(index, node), path: fullPath(index, node, label) };
  });
}

/** Branches to open so that `key` is visible in the tree. */
export const ancestorKeys = (index: NavigationIndex, key: string) =>
  navigationTrail(index, key).slice(0, -1).filter(node => node.kind !== "root").map(node => node.key);
