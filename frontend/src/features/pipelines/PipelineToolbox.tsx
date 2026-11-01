import { useState } from "react";
import type { PipelineComponent } from "./contracts";
import {
  addBlocker, insertBlocker, isMultiInstanceKind, nodeLabel, PIPELINE_LIMITS, type GraphDocument, type Link,
} from "./model";
import { nodeKinds } from "./semantics";

const kinds = ["source", "transform", "merge", "detector", "policy", "output"] as const;
const singleHints: Partial<Record<(typeof kinds)[number], string>> = {
  source: "One per design. Its readings come from the service's Inputs.",
  detector: "One per design. Select it to change the detector model.",
  policy: "One per design. Select it to change its threshold settings.",
  output: "One per design.",
};

export function PipelineToolbox({
  components,
  document,
  link,
  onAdd,
  onSelect,
  onDragStart,
  onDragEnd,
}: {
  components: PipelineComponent[];
  document: GraphDocument;
  /** Inserting on this connection: only the steps that fit it are listed. */
  link?: Link;
  onAdd: (componentId: string) => void;
  /** Opens an existing single-instance component instead of hiding its section. */
  onSelect?: (nodeId: string) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}) {
  const [query, setQuery] = useState("");
  const definition = document.definition;
  const search = query.trim().toLocaleLowerCase();
  const strategyComponents = components.filter((component) =>
    component.strategies.includes(definition.strategy)
    && (!link || !insertBlocker(definition, link, component, components)));
  const matches = strategyComponents.filter((component) =>
    `${component.label} ${component.description} ${nodeKinds[component.kind]}`
      .toLocaleLowerCase()
      .includes(search));
  const full = definition.nodes.length >= PIPELINE_LIMITS.nodes;
  const sections = kinds.map((kind) => {
    const existing = link || isMultiInstanceKind(kind)
      ? undefined : definition.nodes.find((node) => node.kind === kind);
    const items = matches.filter((component) => component.kind === kind);
    return { kind, existing, items };
  }).filter(({ kind, existing, items }) => items.length
    || (existing && (!search || nodeKinds[kind].toLocaleLowerCase().includes(search))));
  return (
    <aside className="pl-toolbox" aria-label="Pipeline toolbox">
      <input
        type="search"
        aria-label="Search components"
        placeholder="Search components…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <p className="pl-toolbox-count" role="status">{definition.nodes.length} / {PIPELINE_LIMITS.nodes}</p>
      {full && <p className="pl-help">The design has reached its {PIPELINE_LIMITS.nodes}-component limit.</p>}
      {sections.map(({ kind, existing, items }) => (
        <section key={kind}>
          <h4>{nodeKinds[kind]}</h4>
          {existing ? <div className="pl-toolbox-existing">
            <p className="pl-help">{singleHints[kind]}</p>
            {onSelect && <button type="button" className="pl-toolbox-item"
              onClick={() => onSelect(existing.id)}>
              <span>Select {nodeLabel(existing, components, document.layout)}</span>
            </button>}
          </div> : items.map((component) => {
            const blocker = link ? undefined : addBlocker(definition, component);
            return <button
              type="button"
              key={component.id}
              className="pl-toolbox-item"
              title={blocker ?? component.description}
              aria-label={`${link ? "Insert" : "Add"} ${component.label}`}
              disabled={!!blocker}
              draggable={!link && !blocker}
              onDragStart={(event) => {
                event.dataTransfer.setData(
                  "application/off-key-component",
                  component.id,
                );
                event.dataTransfer.effectAllowed = "copy";
                onDragStart?.();
              }}
              onDragEnd={onDragEnd}
              onClick={() => onAdd(component.id)}
            >
              <span>{component.label}</span>
            </button>;
          })}
        </section>
      ))}
      {!sections.length && <p className="pl-help">
        {link && !search ? "No component fits this connection." : "No matching components."}
      </p>}
    </aside>
  );
}
