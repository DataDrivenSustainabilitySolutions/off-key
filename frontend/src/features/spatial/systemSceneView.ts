import type { SpatialNode, SpatialWorkspace, Topology } from "./types";

/** Resolved scene edges have presentation IDs, so hierarchy follows entity endpoints. */
function systemParents(
  topology: Topology,
  byId: ReadonlyMap<string, SpatialNode>,
) {
  return new Map(
    topology.edges
      .filter(
        (edge) =>
          edge.id.startsWith("parent:") ||
          (byId.get(edge.source)?.system?.kind === "device" &&
            byId.get(edge.target)?.system?.kind === "device"),
      )
      .map((edge) => [edge.source, edge.target]),
  );
}

/** A personal selection adds context without changing catalog ownership. */
export function scopeSystemTopology(
  topology: Topology,
  members?: ReadonlySet<string>,
): Topology {
  if (!members) return topology;
  const ids = new Set(members);
  const byId = new Map(topology.nodes.map((node) => [node.id, node]));
  const requestedBrokers = new Set(
    topology.nodes
      .filter(
        (node) => members.has(node.id) && node.system?.kind === "connection",
      )
      .map((node) => node.id),
  );
  for (const id of members) {
    const owner = byId.get(id)?.system?.deviceId;
    if (owner) ids.add(owner);
  }
  for (const node of topology.nodes) {
    if (
      node.system?.connectionId &&
      requestedBrokers.has(node.system.connectionId)
    ) {
      ids.add(node.id);
      if (node.system.deviceId) ids.add(node.system.deviceId);
    }
  }
  const children = new Map<string, string[]>();
  for (const [child, parent] of systemParents(topology, byId)) {
    const siblings = children.get(parent) ?? [];
    siblings.push(child);
    children.set(parent, siblings);
  }
  const queue = [...ids];
  for (let index = 0; index < queue.length; index += 1) {
    for (const child of children.get(queue[index]!) ?? []) {
      if (ids.has(child)) continue;
      ids.add(child);
      queue.push(child);
    }
  }
  for (const node of topology.nodes) {
    if (node.system?.deviceId && ids.has(node.system.deviceId))
      ids.add(node.id);
  }
  // Add source brokers last: context must not pull every broker sibling into a group.
  for (const node of topology.nodes) {
    if (ids.has(node.id) && node.system?.connectionId)
      ids.add(node.system.connectionId);
  }
  return {
    nodes: topology.nodes.filter((node) => ids.has(node.id)),
    edges: topology.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target),
    ),
  };
}

/** Membership colors are a view overlay; document groups and topic bindings are intact. */
export function colorSystemTopology(
  topology: Topology,
  workspace: SpatialWorkspace,
  selectedGroupId: string | null,
): Topology {
  if (!workspace.personalGroups?.length) return topology;
  const colors = new Map<string, { color: string; priority: number }>();
  const summaryColors = new Map<string, { color: string; priority: number }>();
  const ordered = [...workspace.personalGroups].sort(
    (a, b) =>
      Number(b.id === selectedGroupId) - Number(a.id === selectedGroupId),
  );
  ordered.forEach((group, priority) => {
    for (const id of group.memberIds)
      if (!colors.has(id)) colors.set(id, { color: group.color, priority });
  });
  const byId = new Map(topology.nodes.map((node) => [node.id, node]));
  const parents = systemParents(topology, byId);
  // A grouped hidden reading must still identify its owner in the overview.
  for (const node of topology.nodes) {
    const membership = colors.get(node.id);
    const owner = node.system?.deviceId;
    const previous = owner ? colors.get(owner) : undefined;
    if (
      membership &&
      owner &&
      (!previous || membership.priority < previous.priority)
    )
      colors.set(owner, membership);
    if (
      membership &&
      !owner &&
      node.system?.kind === "stream" &&
      node.system.connectionId
    ) {
      const broker = node.system.connectionId;
      const previousSummary = summaryColors.get(broker);
      if (!previousSummary || membership.priority < previousSummary.priority)
        summaryColors.set(broker, membership);
    }
  }
  return {
    ...topology,
    nodes: topology.nodes.map((node) => {
      let selected = colors.get(node.id);
      const consider = (id: string | undefined) => {
        const candidate = id ? colors.get(id) : undefined;
        if (candidate && (!selected || candidate.priority < selected.priority))
          selected = candidate;
      };
      consider(node.system?.connectionId);
      let owner = node.system?.deviceId ?? parents.get(node.id);
      const visited = new Set<string>();
      while (owner && !visited.has(owner)) {
        visited.add(owner);
        consider(owner);
        consider(byId.get(owner)?.system?.connectionId);
        owner = parents.get(owner);
      }
      // Summary tint identifies a hidden standalone reading without claiming its broker siblings belong to that group.
      const summary = summaryColors.get(node.id);
      if (summary && (!selected || summary.priority < selected.priority))
        selected = summary;
      return selected ? { ...node, color: selected.color } : node;
    }),
  };
}

/** The configured system always uses catalog-derived placement; saved view state owns only navigation and personal organization. */
export function automaticSystemLayout(
  topology: Topology,
  workspace: SpatialWorkspace,
): SpatialWorkspace {
  return {
    ...workspace,
    layoutMode: "automatic",
    positions: {},
    locks: {},
    memberships: Object.fromEntries(
      topology.nodes.map((node) => [node.id, node.groupId]),
    ),
    groups: workspace.groups.some((group) => group.locked || group.collapsed)
      ? workspace.groups.map((group) => ({
          ...group,
          locked: false,
          collapsed: false,
        }))
      : workspace.groups,
  };
}
