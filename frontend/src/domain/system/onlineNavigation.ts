import type { LiveStatus } from "@/types/system-live";
import type { ExplorerNode, NavigationIndex } from "./navigationIndex";
import { isReadingLeaf, readingActivity, type ReadingActivitySource } from "./readingActivity";

/** Keep receiving leaves and their ancestors without changing the catalogue or selection. */
export function onlineNavigationIndex(index: NavigationIndex, source: ReadingActivitySource, status: LiveStatus, now: number): NavigationIndex {
  const visible = new Set([index.rootKey]);
  const readings = new Set<string>();
  for (const node of index.nodes.values()) {
    if (!isReadingLeaf(node) || !readingActivity(node, source, status, now).receiving) continue;
    for (const id of node.streamIds) readings.add(id);
    let ancestor: ExplorerNode | undefined = node;
    while (ancestor && !visible.has(ancestor.key)) {
      visible.add(ancestor.key);
      ancestor = ancestor.parentKey ? index.nodes.get(ancestor.parentKey) : undefined;
    }
  }

  const nodes = new Map<string, ExplorerNode>();
  const devices = new Set<string>();
  const topics = new Set<string>();
  let connections = 0;
  for (const node of index.nodes.values()) {
    if (!visible.has(node.key)) continue;
    const streamIds = node.streamIds.filter(id => readings.has(id));
    nodes.set(node.key, { ...node, streamIds, children: node.children.filter(key => visible.has(key)) });
    if (node.kind === "connection") connections++;
    if (node.kind === "device" && node.objectId) devices.add(node.objectId);
    if (node.kind === "topic" && streamIds.length) topics.add(JSON.stringify([node.connectionId, node.topic]));
  }
  const objectKeys = new Map<string, string[]>();
  for (const [id, keys] of index.objectKeys) {
    const matches = keys.filter(key => visible.has(key));
    if (matches.length) objectKeys.set(id, matches);
  }
  return { rootKey: index.rootKey, nodes, objectKeys,
    counts: { connections, devices: devices.size, topics: topics.size, readings: readings.size } };
}
