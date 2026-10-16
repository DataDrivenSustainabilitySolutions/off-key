import type { JsonValue } from "@/types/monitoring";
import type {
  PipelineDefinition,
  PipelineLayout,
  PipelineNode,
  PipelineComponent,
} from "./contracts";

export type GraphDocument = {
  definition: PipelineDefinition;
  layout: PipelineLayout;
};

export function nodeLabel(
  node: PipelineNode | undefined,
  components: PipelineComponent[],
  layout?: PipelineLayout,
): string {
  if (!node) return "Missing component";
  return (
    layout?.nodes[node.id]?.label ||
    components.find((item) => item.id === node.component)?.label ||
    node.component
  );
}

export function nodeOptionLabel(
  node: PipelineNode | undefined,
  document: GraphDocument,
  components: PipelineComponent[],
): string {
  const label = nodeLabel(node, components, document.layout);
  return node &&
    document.definition.nodes.filter(
      (item) => nodeLabel(item, components, document.layout) === label,
    ).length > 1
    ? `${label} · ${node.id}`
    : label;
}

/** Node IDs and slot IDs are stable; displayed labels never enter connections. */
export function nextNodeId(nodes: PipelineNode[], component: string): string {
  const prefix = component.replace(/[^a-zA-Z0-9_-]/g, "_");
  let suffix = 1;
  while (nodes.some((node) => node.id === `${prefix}_${suffix}`)) suffix++;
  return `${prefix}_${suffix}`;
}

export function addComponent(
  document: GraphDocument,
  component: PipelineComponent,
): GraphDocument {
  if (
    document.definition.nodes.length >= 64 ||
    !component.strategies.includes(document.definition.strategy) ||
    (component.kind !== "transform" &&
      component.kind !== "merge" &&
      document.definition.nodes.some((node) => node.kind === component.kind))
  )
    return document;
  const id = nextNodeId(document.definition.nodes, component.id);
  const instance =
    document.definition.nodes.filter((node) => node.component === component.id)
      .length + 1;
  const params = Object.fromEntries(
    component.fields
      .filter((field) => field.default !== undefined)
      .map((field) => [field.name, field.default as JsonValue]),
  );
  return {
    definition: {
      ...document.definition,
      nodes: [
        ...document.definition.nodes,
        {
          id,
          kind: component.kind,
          component: component.id,
          contract_version: component.contract_version ?? 1,
          params,
        },
      ],
    },
    layout: {
      ...document.layout,
      nodes: {
        ...document.layout.nodes,
        [id]: {
          x: 200 + document.definition.nodes.length * 25,
          y: 100 + document.definition.nodes.length * 30,
          ...(instance > 1 ? { label: `${component.label} ${instance}` } : {}),
        },
      },
    },
  };
}

export function removeNode(document: GraphDocument, id: string): GraphDocument {
  const positions = { ...document.layout.nodes };
  delete positions[id];
  return {
    definition: {
      ...document.definition,
      nodes: document.definition.nodes.filter((node) => node.id !== id),
      edges: document.definition.edges.filter(
        (edge) => edge.source !== id && edge.target !== id,
      ),
    },
    layout: { ...document.layout, nodes: positions },
  };
}

export function connectNodes(
  definition: PipelineDefinition,
  source: string,
  target: string,
): PipelineDefinition {
  if (
    source === target ||
    definition.edges.some(
      (edge) => edge.source === source && edge.target === target,
    )
  )
    return definition;
  const node = definition.nodes.find((item) => item.id === target);
  if (!node || !definition.nodes.some((item) => item.id === source))
    return definition;
  if (node.kind === "source") return definition;
  if (
    node.kind !== "merge" &&
    definition.edges.some((edge) => edge.target === target)
  )
    return definition;
  const reachable = new Set([target]);
  for (let changed = true; changed; ) {
    changed = false;
    for (const edge of definition.edges)
      if (reachable.has(edge.source) && !reachable.has(edge.target)) {
        reachable.add(edge.target);
        changed = true;
      }
  }
  if (reachable.has(source)) return definition;
  const order =
    Math.max(
      -1,
      ...definition.edges
        .filter((edge) => edge.target === target)
        .map((edge) => edge.order),
    ) + 1;
  return {
    ...definition,
    edges: [...definition.edges, { source, target, order }],
  };
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value) ?? "null";
}

function effectiveParameters(
  node: PipelineNode,
  definition: PipelineDefinition,
  components: PipelineComponent[],
) {
  const defaults = Object.fromEntries(
    (components.find((item) => item.id === node.component)?.fields ?? [])
      .filter((field) => field.default !== undefined)
      .map((field) => [field.name, field.default]),
  );
  const params = { ...defaults, ...node.params };
  if (
    (node.component.endsWith("random_projection") ||
      node.component === "static.pca") &&
    params.seed == null
  )
    params.seed = definition.settings.seed;
  return params;
}

export function executableChanges(
  before: PipelineDefinition,
  after: PipelineDefinition,
  components: PipelineComponent[] = [],
): string[] {
  const changes: string[] = [];
  if (before.strategy !== after.strategy)
    changes.push(`Strategy: ${before.strategy} → ${after.strategy}`);
  const slots = (definition: PipelineDefinition) =>
    definition.input_slots.map((slot) => ({
      id: slot.id,
      unit: slot.unit ?? null,
    }));
  if (canonical(slots(before)) !== canonical(slots(after)))
    changes.push("Input slots or expected units changed");
  const previous = new Map(before.nodes.map((node) => [node.id, node]));
  for (const node of after.nodes) {
    const old = previous.get(node.id);
    if (!old) changes.push(`Added ${node.component}`);
    else if (
      old.component !== node.component ||
      (old.contract_version ?? 1) !== (node.contract_version ?? 1) ||
      canonical(effectiveParameters(old, before, components)) !==
        canonical(effectiveParameters(node, after, components))
    )
      changes.push(`Updated ${node.component} (${node.id})`);
    previous.delete(node.id);
  }
  for (const node of previous.values())
    changes.push(`Removed ${node.component}`);
  const edges = (definition: PipelineDefinition) =>
    [...definition.edges].sort((left, right) =>
      `${left.target}:${left.order}:${left.source}`.localeCompare(
        `${right.target}:${right.order}:${right.source}`,
      ),
    );
  if (canonical(edges(before)) !== canonical(edges(after)))
    changes.push("Feature connections or merge order changed");
  if (canonical(before.settings) !== canonical(after.settings))
    changes.push("Learning or calibration settings changed");
  return changes;
}

export function moveMergeInput(
  definition: PipelineDefinition,
  target: string,
  index: number,
  direction: -1 | 1,
): PipelineDefinition {
  const incoming = definition.edges
    .filter((edge) => edge.target === target)
    .sort((left, right) => left.order - right.order);
  const next = index + direction;
  if (!incoming[index] || !incoming[next]) return definition;
  [incoming[index], incoming[next]] = [incoming[next]!, incoming[index]!];
  return {
    ...definition,
    edges: [
      ...definition.edges.filter((edge) => edge.target !== target),
      ...incoming.map((edge, order) => ({ ...edge, order })),
    ],
  };
}
