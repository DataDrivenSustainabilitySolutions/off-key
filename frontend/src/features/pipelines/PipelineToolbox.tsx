import { useId, useRef, useState, type KeyboardEvent } from "react";
import type { PipelineComponent } from "./contracts";
import {
  addBlocker, insertBlocker, isMultiInstanceKind, nodeLabel, PIPELINE_LIMITS, type GraphDocument, type Link,
} from "./model";
import { familyLabel, STEP_FAMILIES, stepDescription, stepFamily } from "./steps";

const singleNames: Record<string, string> = { detector: "detector", policy: "policy", output: "output" };
const listed = (names: string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

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
  /** Opens a one-per-pipeline step that is already present; it is not offered again. */
  onSelect?: (nodeId: string) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}) {
  const [query, setQuery] = useState("");
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const definition = document.definition;
  const search = query.trim().toLocaleLowerCase();
  const offered = components.filter((component) =>
    component.strategies.includes(definition.strategy)
    && (isMultiInstanceKind(component.kind) || !definition.nodes.some((node) => node.kind === component.kind))
    && (!link || !insertBlocker(definition, link, component, components)));
  const matches = offered.filter((component) =>
    `${component.label} ${stepDescription(component)} ${component.description} ${familyLabel(stepFamily(component.kind, component.id))}`
      .toLocaleLowerCase()
      .includes(search));
  const sections = STEP_FAMILIES
    .map((family) => ({ ...family, items: matches.filter((component) => stepFamily(component.kind, component.id) === family.id) }))
    .filter((section) => section.items.length);
  // The detector, policy and output are changed in their own settings, not added again.
  const present = link ? [] : definition.nodes.filter((node) => node.kind in singleNames
    && (!search || `${nodeLabel(node, components, document.layout)} ${singleNames[node.kind]}`.toLocaleLowerCase().includes(search)));
  const presentText = listed(present.map((node) => singleNames[node.kind]!));
  const full = definition.nodes.length >= PIPELINE_LIMITS.nodes;
  const blocker = (component: PipelineComponent) => link ? undefined : addBlocker(definition, component);
  const items = () => [...list.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []];
  const focusItem = (index: number) => {
    const all = items();
    all[Math.max(0, Math.min(all.length - 1, index))]?.focus();
  };
  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = items();
    const index = all.indexOf(event.target as HTMLButtonElement);
    if (index < 0) return;
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (step === -1 && index === 0) list.current?.parentElement?.querySelector<HTMLInputElement>("input[type=search]")?.focus();
    else if (step) focusItem(index + step);
    else if (event.key === "Home") focusItem(0);
    else if (event.key === "End") focusItem(all.length - 1);
    else return;
    event.preventDefault();
  };
  return (
    <aside className="pl-toolbox" aria-label="Pipeline toolbox">
      <input
        type="search"
        aria-label="Search steps"
        placeholder="Search steps…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            focusItem(0);
          } else if (event.key === "Enter") {
            const first = sections.flatMap((section) => section.items).find((component) => !blocker(component));
            if (!first) return;
            event.preventDefault();
            onAdd(first.id);
          }
        }}
      />
      <p className="pl-toolbox-count" role="status">{definition.nodes.length} / {PIPELINE_LIMITS.nodes}</p>
      {full && <p className="pl-help">This pipeline has reached its {PIPELINE_LIMITS.nodes}-step limit.</p>}
      <div ref={list} onKeyDown={navigate}>
        {sections.map((section) => (
          <section key={section.id} aria-labelledby={`${id}-${section.id}`}>
            <h4 id={`${id}-${section.id}`}>{section.label}</h4>
            <div className="pl-toolbox-grid">
              {section.items.map((component) => {
                const reason = blocker(component);
                return <button
                  type="button"
                  key={component.id}
                  className="pl-toolbox-item"
                  title={reason}
                  aria-label={`${link ? "Insert" : "Add"} ${component.label}`}
                  aria-describedby={`${id}-${component.id}`}
                  disabled={!!reason}
                  draggable={!link && !reason}
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
                  <strong>{component.label}</strong>
                  <small id={`${id}-${component.id}`}>{stepDescription(component)}</small>
                </button>;
              })}
            </div>
          </section>
        ))}
        {present.length > 0 && <div className="pl-toolbox-present">
          <p className="pl-help">
            The {presentText} {present.length === 1 ? "is" : "are"} already in this pipeline.
            {onSelect ? ` Open ${present.length === 1 ? "it" : "one"} to change it.` : ""}
          </p>
          {onSelect && <div>
            {present.map((node) => {
              const label = nodeLabel(node, components, document.layout);
              return <button type="button" key={node.id} aria-label={`Select ${label}`} onClick={() => onSelect(node.id)}>{label}</button>;
            })}
          </div>}
        </div>}
      </div>
      {!sections.length && !present.length && <p className="pl-help">
        {link && !search ? "No step fits this connection." : "No matching steps."}
      </p>}
    </aside>
  );
}
