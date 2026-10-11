import type { SpatialGroup, SpatialNode, Topology } from "./types";

export type PulseRoute = { source: string; target: string };
export type FocusedSystemTopology = {
  topology: Topology;
  groups: SpatialGroup[];
  pulseSources: Record<string, string>;
  pulseRoutes: Record<string, PulseRoute>;
  focusedDeviceId: string | null;
  hiddenStreams: number;
};

/** Keep the structural overview compact; reveal the selected reading without changing its placement. */
export function focusSystemTopology(
  topology: Topology,
  selectedId: string | null,
  options: { showStreams?: boolean; streamLimit?: number } = {},
): FocusedSystemTopology {
  const byId = new Map(topology.nodes.map((node) => [node.id, node]));
  const selected = selectedId ? byId.get(selectedId) : undefined;
  const focusedDeviceId =
    selected?.system?.kind === "device"
      ? selected.id
      : (selected?.system?.deviceId ?? null);
  const requestedLimit = options.streamLimit ?? 48;
  const limit = Number.isFinite(requestedLimit)
    ? Math.max(1, Math.min(96, Math.floor(requestedLimit)))
    : 48;
  const revealMeasurements = options.showStreams === true;
  const streams = topology.nodes.filter(
    (node) => node.system?.kind === "stream",
  );
  const reveal = new Set<string>();
  // Keep the selected measurement discoverable even if it lies outside the bounded first page.
  if (selected?.system?.kind === "stream") reveal.add(selected.id);
  if (revealMeasurements) {
    for (const stream of streams) {
      const matchesFocus = focusedDeviceId
        ? stream.system?.deviceId === focusedDeviceId
        : selected?.system?.kind === "connection" &&
          !stream.system?.deviceId &&
          stream.system?.connectionId === selected.id;
      if (!matchesFocus || reveal.has(stream.id)) continue;
      if (reveal.size >= limit) break;
      reveal.add(stream.id);
    }
  }
  const primaryBroker = new Map<string, string>();
  for (const node of topology.nodes) {
    if (node.system?.kind === "device" && node.system.connectionId)
      primaryBroker.set(node.id, node.system.connectionId);
  }
  for (const stream of streams) {
    const owner = stream.system?.deviceId;
    const broker = stream.system?.connectionId;
    if (owner && broker && !primaryBroker.has(owner))
      primaryBroker.set(owner, broker);
  }
  const occupiedRegionIds = new Set(
    topology.nodes
      .filter((node) => node.kind === "broker")
      .map((node) => `system-region:${node.id}`),
  );
  let unboundRegionId = "system-region:unbound";
  while (occupiedRegionIds.has(unboundRegionId)) unboundRegionId += ":";
  const structuralGroupId = (node: SpatialNode) => {
    const broker =
      node.kind === "broker"
        ? node.id
        : node.system?.kind === "device"
          ? primaryBroker.get(node.id)
          : node.system?.deviceId
            ? primaryBroker.get(node.system.deviceId)
            : node.system?.connectionId;
    return broker ? `system-region:${broker}` : unboundRegionId;
  };
  const nodes = topology.nodes
    .filter((node) => node.system?.kind !== "stream" || reveal.has(node.id))
    .map((node) => ({ ...node, groupId: structuralGroupId(node) }));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = topology.edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
  );
  const pulseSources = Object.fromEntries(
    streams.map((stream) => [
      stream.id,
      visibleIds.has(stream.id)
        ? stream.id
        : (stream.system?.deviceId ?? stream.system?.connectionId ?? stream.id),
    ]),
  );
  const pulseRoutes = Object.fromEntries(
    streams.flatMap((stream) => {
      const source = pulseSources[stream.id];
      const target = stream.system?.connectionId;
      return source &&
        target &&
        visibleIds.has(source) &&
        visibleIds.has(target)
        ? [[stream.id, { source, target }]]
        : [];
    }),
  );
  const counts = new Map<string, number>();
  for (const node of nodes)
    counts.set(node.groupId, (counts.get(node.groupId) ?? 0) + 1);
  const groups: SpatialGroup[] = topology.nodes
    .filter((node) => node.kind === "broker")
    .map((node) => ({
      id: structuralGroupId(node),
      name: node.label,
      color: "#8396a5",
      collapsed: false,
      locked: false,
    }))
    .filter((group) => counts.has(group.id));
  if (counts.has(unboundRegionId))
    groups.push({
      id: unboundRegionId,
      name: "Unbound entities",
      color: "#98a1a9",
      collapsed: false,
      locked: false,
    });
  return {
    topology: { nodes, edges },
    groups,
    pulseSources,
    pulseRoutes,
    focusedDeviceId,
    hiddenStreams:
      streams.length -
      nodes.filter((node) => node.system?.kind === "stream").length,
  };
}
