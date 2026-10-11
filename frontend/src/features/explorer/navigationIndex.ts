import type { SystemDocument } from "@/features/spatial/systemTypes";

export type ExplorerNode = {
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
  searchText: string;
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
const rootKey = identity("root");
const unassignedKey = identity("unassigned");

/** Build once per catalogue revision, independently of live telemetry. */
export function buildNavigationIndex(document: SystemDocument): NavigationIndex {
  const nodes = new Map<string, ExplorerNode>();
  const objectKeys = new Map<string, string[]>();
  const devices = new Map(document.devices.map((device) => [device.id, device]));
  const connections = new Set(document.connections.map((connection) => connection.id));
  const deviceContexts = new Map<string, Set<string | null>>();
  const topicIdentities = new Set<string>();
  const bindingSearch = new Map<string, string[]>();
  const topicContexts = new Map<string, string>();

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
      addNode(emptyNode(unassignedKey, "unassigned", "Unassigned entities", rootKey));
    }
    return unassignedKey;
  };
  const addContext = (deviceId: string, connectionId: string | null) => {
    const contexts = deviceContexts.get(deviceId);
    if (contexts) contexts.add(connectionId);
    else deviceContexts.set(deviceId, new Set([connectionId]));
  };

  addNode(emptyNode(rootKey, "root", document.label || "Aberration", null));
  for (const connection of document.connections) {
    addNode({
      ...emptyNode(identity("connection", connection.id), "connection", connection.label, rootKey),
      objectId: connection.id,
      entityKind: "connection",
      connectionId: connection.id,
    });
  }
  for (const device of document.devices) {
    if (device.connection_id && connections.has(device.connection_id)) {
      addContext(device.id, device.connection_id);
    }
  }
  for (const stream of document.streams) {
    if (stream.device_id && devices.has(stream.device_id)) {
      addContext(stream.device_id, connections.has(stream.connection_id) ? stream.connection_id : null);
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

  for (const stream of document.streams) {
    const connectionId = connections.has(stream.connection_id) ? stream.connection_id : null;
    const contextKey = stream.device_id && devices.has(stream.device_id)
      ? identity("device", connectionId, stream.device_id)
      : connectionId === null ? ensureUnassigned() : identity("connection", connectionId);
    nodes.get(rootKey)!.streamIds.push(stream.id);
    const connectionKey = connectionId === null ? ensureUnassigned() : identity("connection", connectionId);
    nodes.get(connectionKey)!.streamIds.push(stream.id);
    if (contextKey !== connectionKey) nodes.get(contextKey)!.streamIds.push(stream.id);
    topicIdentities.add(identity(stream.connection_id, stream.topic));
    let parentKey = contextKey;
    let prefix = "";
    const segments = stream.topic.split("/");
    for (let position = 0; position < segments.length; position += 1) {
      const segment = segments[position]!;
      prefix = position === 0 ? segment : `${prefix}/${segment}`;
      const key = identity("topic", contextKey, prefix);
      if (!nodes.has(key)) {
        addNode({
          ...emptyNode(key, "topic", segment || "(empty level)", parentKey),
          connectionId: stream.connection_id,
          deviceId: stream.device_id,
          topic: prefix,
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

  const streams = new Map(document.streams.map((stream) => [stream.id, stream]));
  // Reading leaves make a topic that is both an endpoint and a parent unambiguous.
  for (const endpoint of Array.from(nodes.values())) {
    if (endpoint.kind !== "topic" || endpoint.streamIds.length === 0) continue;
    if (endpoint.streamIds.length === 1 && endpoint.children.length === 0) {
      endpoint.objectId = endpoint.streamIds[0]!;
      endpoint.entityKind = "stream";
      addObjectKey(endpoint.objectId, endpoint.key);
      continue;
    }
    for (const streamId of endpoint.streamIds) {
      const stream = streams.get(streamId)!;
      const node = addNode({
        ...emptyNode(identity("reading", endpoint.key, stream.id), "reading", stream.label, endpoint.key),
        objectId: stream.id,
        entityKind: "stream",
        connectionId: stream.connection_id,
        deviceId: stream.device_id,
        topic: stream.topic,
        streamIds: [stream.id],
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
    node.searchText = [ancestry, node.label, node.topic ?? "", ...(bindingSearch.get(node.key) ?? [])].join(" ").toLocaleLowerCase();
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
      connections: document.connections.length,
      devices: document.devices.length,
      topics: topicIdentities.size,
      readings: document.streams.length,
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

export function searchNavigation(index: NavigationIndex, query: string, limit = 100): ExplorerNode[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0 || !Number.isFinite(limit) || limit <= 0) return [];
  const maximum = Math.floor(limit);
  if (maximum === 0) return [];
  const results: ExplorerNode[] = [];
  // A deep path must not fill the result limit with its intermediate folders
  // before its actual reading becomes discoverable.
  for (const selectable of [true, false]) {
    for (const node of index.nodes.values()) {
      if (node.kind === "root" || node.kind === "unassigned" || Boolean(node.objectId) !== selectable) continue;
      if (terms.every((term) => node.searchText.includes(term))) {
        results.push(node);
        if (results.length === maximum) return results;
      }
    }
  }
  return results;
}
