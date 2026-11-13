import type { SystemDocument } from "@/types/system";
import type { SourceAppearance } from "@/types/source-appearance";

export type ExplorerNode = {
  appearance?: SourceAppearance;
  color?: string;
  key: string;
  kind: "root" | "connection" | "device" | "topic" | "reading" | "unassigned";
  label: string;
  objectId?: string;
  entityKind?: "connection" | "device" | "stream";
  connectionId?: string;
  deviceId?: string;
  topic?: string;
  /** Topic nodes contain their own bindings; other nodes contain their subtree. */
  streamIds: string[];
  parentKey: string | null;
  children: string[];
  /** Lower-cased ancestry followed by the node's own label and identifiers. */
  searchText: string;
  /** Where the node's own part of `searchText` starts, after its ancestry. */
  searchOwnStart?: number;
  /** Lower-cased label as the explorer shows it, for ranking matches. */
  searchLabel?: string;
};

export type NavigationIndex = {
  rootKey: string;
  nodes: Map<string, ExplorerNode>;
  objectKeys: Map<string, string[]>;
  counts: { connections: number; devices: number; topics: number; readings: number };
};

export type NavigationRow = {
  node: ExplorerNode;
  label: string;
  trailKeys: string[];
};

const naturalOrder = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});
const identity = (...parts: unknown[]): string => JSON.stringify(parts);
/**
 * The levels of an address. An MQTT topic splits at every slash. An HTTP request
 * path keeps its leading slash on the first level and its query on the last.
 */
function addressLevels(address: string, polled: boolean): string[] {
  if (!polled || !address.startsWith("/")) return address.split("/");
  const query = address.indexOf("?");
  const levels = (query < 0 ? address : address.slice(0, query)).split("/").slice(1);
  levels[0] = `/${levels[0]}`;
  if (query >= 0) levels[levels.length - 1] += address.slice(query);
  return levels;
}
const rootKey = identity("root");
const unassignedKey = identity("unassigned");

/** Build once per catalogue revision, independently of live telemetry. */
export function buildNavigationIndex(document: SystemDocument): NavigationIndex {
  const nodes = new Map<string, ExplorerNode>();
  const objectKeys = new Map<string, string[]>();
  const devices = new Map(document.devices.map((device) => [device.id, device]));
  const connections = new Set(document.brokers.map((connection) => connection.id));
  const polled = new Set(document.brokers.filter((connection) => connection.protocol === "http").map((connection) => connection.id));
  const deviceContexts = new Map<string, Set<string | null>>();
  const topicIdentities = new Set<string>();
  const bindingSearch = new Map<string, string[]>();
  const topicContexts = new Map<string, string>();
  const topicAppearances = new Map((document.topic_appearances ?? []).map(item => [identity(item.broker_id, item.topic), item.appearance]));

  const addObjectKey = (objectId: string, key: string) => {
    const references = objectKeys.get(objectId);
    if (references) references.push(key);
    else objectKeys.set(objectId, [key]);
  };
  const addNode = (node: ExplorerNode) => {
    nodes.set(node.key, node);
    if (node.objectId) addObjectKey(node.objectId, node.key);
    if (node.parentKey) nodes.get(node.parentKey)?.children.push(node.key);
    return node;
  };
  const emptyNode = (
    key: string,
    kind: ExplorerNode["kind"],
    label: string,
    parentKey: string | null,
  ): ExplorerNode => ({ key, kind, label, parentKey, children: [], streamIds: [], searchText: "" });
  const ensureUnassigned = () => {
    if (!nodes.has(unassignedKey)) {
      addNode(emptyNode(unassignedKey, "unassigned", "Unassigned devices", rootKey));
    }
    return unassignedKey;
  };
  const addContext = (deviceId: string, connectionId: string | null) => {
    const contexts = deviceContexts.get(deviceId);
    if (contexts) contexts.add(connectionId);
    else deviceContexts.set(deviceId, new Set([connectionId]));
  };

  addNode(emptyNode(rootKey, "root", document.label || "Aberration", null));
  for (const connection of document.brokers) {
    addNode({
      ...emptyNode(identity("connection", connection.id), "connection", connection.label, rootKey),
      objectId: connection.id,
      entityKind: "connection",
      connectionId: connection.id,
      appearance: connection.appearance,
    });
  }
  for (const device of document.devices) {
    if (device.broker_id && connections.has(device.broker_id)) {
      addContext(device.id, device.broker_id);
    }
  }
  for (const stream of document.readings) {
    if (stream.device_id && devices.has(stream.device_id)) {
      addContext(stream.device_id, connections.has(stream.broker_id) ? stream.broker_id : null);
    }
  }
  for (const device of document.devices) {
    if (!deviceContexts.has(device.id)) addContext(device.id, null);
  }

  // Create every context before attaching parents: document ordering is irrelevant.
  for (const device of document.devices) {
    for (const connectionId of deviceContexts.get(device.id)!) {
      addNode({
        ...emptyNode(identity("device", connectionId, device.id), "device", device.label, null),
        objectId: device.id,
        entityKind: "device",
        connectionId: connectionId ?? undefined,
        deviceId: device.id,
        appearance: device.appearance,
      });
    }
  }
  for (const device of document.devices) {
    for (const connectionId of deviceContexts.get(device.id)!) {
      const node = nodes.get(identity("device", connectionId, device.id))!;
      const parentKey = device.parent_id
        ? identity("device", connectionId, device.parent_id)
        : null;
      node.parentKey = parentKey && parentKey !== node.key && nodes.has(parentKey)
        ? parentKey
        : connectionId === null ? ensureUnassigned() : identity("connection", connectionId);
    }
  }
  // Valid catalogues are acyclic. This also keeps malformed imported data navigable.
  const settled = new Set<string>();
  for (const start of nodes.values()) {
    if (start.kind !== "device" || settled.has(start.key)) continue;
    const path = new Set<string>();
    let current: ExplorerNode | undefined = start;
    while (current?.kind === "device" && !settled.has(current.key)) {
      if (path.has(current.key)) {
        current.parentKey = current.connectionId
          ? identity("connection", current.connectionId)
          : ensureUnassigned();
        break;
      }
      path.add(current.key);
      current = current.parentKey ? nodes.get(current.parentKey) : undefined;
    }
    for (const key of path) settled.add(key);
  }
  for (const node of nodes.values()) {
    if (node.kind === "device" && node.parentKey) nodes.get(node.parentKey)!.children.push(node.key);
  }

  for (const stream of document.readings) {
    const connectionId = connections.has(stream.broker_id) ? stream.broker_id : null;
    const contextKey = stream.device_id && devices.has(stream.device_id)
      ? identity("device", connectionId, stream.device_id)
      : connectionId === null ? ensureUnassigned() : identity("connection", connectionId);
    nodes.get(rootKey)!.streamIds.push(stream.id);
    const connectionKey = connectionId === null ? ensureUnassigned() : identity("connection", connectionId);
    nodes.get(connectionKey)!.streamIds.push(stream.id);
    if (contextKey !== connectionKey) nodes.get(contextKey)!.streamIds.push(stream.id);
    topicIdentities.add(identity(stream.broker_id, stream.topic));
    let parentKey = contextKey;
    let prefix = "";
    const segments = addressLevels(stream.topic, polled.has(stream.broker_id));
    for (let position = 0; position < segments.length; position += 1) {
      const segment = segments[position]!;
      prefix = position === 0 ? segment : `${prefix}/${segment}`;
      const key = identity("topic", contextKey, prefix);
      if (!nodes.has(key)) {
        addNode({
          ...emptyNode(key, "topic", segment || "(empty level)", parentKey),
          connectionId: stream.broker_id,
          deviceId: stream.device_id,
          topic: prefix,
          appearance: topicAppearances.get(identity(stream.broker_id, prefix)),
        });
        topicContexts.set(key, contextKey);
      }
      parentKey = key;
    }
    const endpoint = nodes.get(parentKey)!;
    endpoint.streamIds.push(stream.id);
    const text = [stream.label, stream.payload_pointer ?? "", stream.category, stream.value_type, stream.unit ?? ""].join(" ");
    const search = bindingSearch.get(endpoint.key);
    if (search) search.push(text);
    else bindingSearch.set(endpoint.key, [text]);
  }

  const streams = new Map(document.readings.map((stream) => [stream.id, stream]));
  // Reading leaves make a topic that is both an endpoint and a parent unambiguous.
  for (const endpoint of Array.from(nodes.values())) {
    if (endpoint.kind !== "topic" || endpoint.streamIds.length === 0) continue;
    if (endpoint.streamIds.length === 1 && endpoint.children.length === 0) {
      endpoint.objectId = endpoint.streamIds[0]!;
      endpoint.entityKind = "stream";
      endpoint.appearance = streams.get(endpoint.objectId)!.appearance ?? endpoint.appearance;
      // The explorer shows the reading's name here rather than its topic segment.
      endpoint.searchLabel = streams.get(endpoint.objectId)!.label.toLocaleLowerCase();
      addObjectKey(endpoint.objectId, endpoint.key);
      continue;
    }
    for (const streamId of endpoint.streamIds) {
      const stream = streams.get(streamId)!;
      const node = addNode({
        ...emptyNode(identity("reading", endpoint.key, stream.id), "reading", stream.label, endpoint.key),
        objectId: stream.id,
        entityKind: "stream",
        connectionId: stream.broker_id,
        deviceId: stream.device_id,
        topic: stream.topic,
        streamIds: [stream.id],
        appearance: stream.appearance,
      });
      bindingSearch.set(node.key, [stream.label, stream.payload_pointer ?? "", stream.category, stream.value_type, stream.unit ?? ""]);
      topicContexts.set(node.key, topicContexts.get(endpoint.key)!);
    }
  }

  const compareNodes = (leftKey: string, rightKey: string) => {
    const left = nodes.get(leftKey)!;
    const right = nodes.get(rightKey)!;
    const groupOrder = (kind: ExplorerNode["kind"]) => kind === "device" ? 0 : kind === "unassigned" ? 2 : 1;
    return groupOrder(left.kind) - groupOrder(right.kind)
      || naturalOrder.compare(left.label, right.label)
      || (left.key < right.key ? -1 : left.key > right.key ? 1 : 0);
  };
  for (const node of nodes.values()) node.children.sort(compareNodes);

  // Preorder gives search deterministic hierarchy order without sorting every query.
  const orderedNodes = new Map<string, ExplorerNode>();
  const stack: ExplorerNode[] = [nodes.get(rootKey)!];
  while (stack.length) {
    const node = stack.pop()!;
    const contextKey = topicContexts.get(node.key);
    const ancestry = contextKey
      ? orderedNodes.get(contextKey)?.searchText ?? ""
      : node.parentKey ? orderedNodes.get(node.parentKey)?.searchText ?? "" : "";
    node.searchText = [ancestry, node.label, node.objectId ?? "", node.deviceId ?? "", node.connectionId ?? "", node.topic ?? "", ...(bindingSearch.get(node.key) ?? [])].join(" ").toLocaleLowerCase();
    node.searchOwnStart = ancestry.length;
    node.searchLabel ??= node.label.toLocaleLowerCase();
    orderedNodes.set(node.key, node);
    for (let position = node.children.length - 1; position >= 0; position -= 1) {
      stack.push(nodes.get(node.children[position]!)!);
    }
  }
  // Only device scopes inherit their child devices' bindings. Topic chains do not
  // allocate copies of descendant IDs, even for very deep MQTT paths.
  for (const node of Array.from(orderedNodes.values()).reverse()) {
    if (node.kind !== "device" || !node.parentKey) continue;
    const parent = orderedNodes.get(node.parentKey)!;
    if (parent.kind === "device") {
      for (const id of node.streamIds) parent.streamIds.push(id);
    }
  }

  return {
    rootKey,
    nodes: orderedNodes,
    objectKeys,
    counts: {
      connections: document.brokers.length,
      devices: document.devices.length,
      topics: topicIdentities.size,
      readings: document.readings.length,
    },
  };
}

export function navigationTrail(index: NavigationIndex, key: string): ExplorerNode[] {
  const trail: ExplorerNode[] = [];
  let node = index.nodes.get(key);
  while (node) {
    trail.push(node);
    node = node.parentKey ? index.nodes.get(node.parentKey) : undefined;
  }
  return trail.reverse();
}

/** A compressed row still carries every traversed key for ancestry and reveal. */
export function navigationRows(index: NavigationIndex, key: string): NavigationRow[] {
  const parent = index.nodes.get(key);
  if (!parent) return [];
  return parent.children.map((childKey) => {
    let node = index.nodes.get(childKey)!;
    const labels = [node.label];
    const trailKeys = [node.key];
    while (node.kind === "topic" && node.streamIds.length === 0 && node.children.length === 1) {
      const child = index.nodes.get(node.children[0]!)!;
      if (child.kind !== "topic") break;
      node = child;
      labels.push(node.label);
      trailKeys.push(node.key);
    }
    return { node, label: labels.join("/"), trailKeys };
  });
}

const wordCharacter = /[\p{L}\p{N}]/u;
const isBoundary = (text: string, position: number) => position < 0 || position >= text.length || !wordCharacter.test(text[position]!);

type SearchTerm = { text: string; numeric: boolean };

/**
 * How well one search term describes a node: its whole label, the start of the
 * label, a whole word in it, the start or end of a word, anywhere in it, one of its
 * own identifiers, or only an ancestor. Digits favour the end of a number, since
 * long serial numbers differ in their last digits.
 */
function termScore(node: ExplorerNode, label: string, { text, numeric }: SearchTerm): number {
  if (label === text) return 60;
  let best = 0;
  for (let position = label.indexOf(text); position >= 0 && best < 50; position = label.indexOf(text, position + 1)) {
    const starts = isBoundary(label, position - 1);
    const ends = isBoundary(label, position + text.length);
    const score = position === 0 ? 50
      : starts && ends ? 45
        : starts ? (numeric ? 40 : 42)
          : ends ? (numeric ? 42 : 35)
            : 30;
    if (score > best) best = score;
  }
  if (best) return best;
  return node.searchText.includes(text, node.searchOwnStart ?? 0) ? 10 : 1;
}

type RankedNode = { node: ExplorerNode; score: number; selectable: boolean };
// Better matches first; then entities before folders; then catalogue order, which
// insertion keeps because a later node never outranks an equal earlier one.
const outranks = (left: RankedNode, right: RankedNode) =>
  left.score > right.score || (left.score === right.score && left.selectable && !right.selectable);

/**
 * Nodes matching every whitespace-separated term anywhere in their path, labels or
 * identifiers, best matches first. Keeps only the best `limit` while scanning, so a
 * broad query over a large catalogue costs one pass and no full sort.
 */
export function searchNavigation(index: NavigationIndex, query: string, limit = 100): ExplorerNode[] {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const terms = words.map((text): SearchTerm => ({ text, numeric: /^\d+$/.test(text) }));
  const phrase = words.join(" ");
  if (terms.length === 0 || !Number.isFinite(limit) || limit <= 0) return [];
  const maximum = Math.floor(limit);
  if (maximum === 0) return [];
  const ranked: RankedNode[] = [];
  for (const node of index.nodes.values()) {
    if (node.kind === "root" || node.kind === "unassigned") continue;
    if (!words.every((word) => node.searchText.includes(word))) continue;
    const label = node.searchLabel ?? node.label.toLocaleLowerCase();
    // A label that reads exactly like the whole query beats one matching each word.
    let score = terms.length > 1 && label === phrase ? 100 : 0;
    for (const term of terms) score += termScore(node, label, term);
    const candidate = { node, score, selectable: Boolean(node.objectId) };
    if (ranked.length === maximum && !outranks(candidate, ranked[maximum - 1]!)) continue;
    let low = 0;
    let high = ranked.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (outranks(candidate, ranked[middle]!)) high = middle;
      else low = middle + 1;
    }
    ranked.splice(low, 0, candidate);
    if (ranked.length > maximum) ranked.pop();
  }
  return ranked.map((entry) => entry.node);
}
