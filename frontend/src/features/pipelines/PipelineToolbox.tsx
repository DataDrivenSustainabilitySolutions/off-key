import { useId, useRef, useState, type KeyboardEvent } from "react";
import type { PipelineComponent } from "./contracts";
import {
  addBlocker, insertBlocker, isMultiInstanceKind, nodeLabel, PIPELINE_LIMITS, type GraphDocument, type Link,
} from "./model";
import { blockedBy, type BlockChoice } from "./blocks";
import { learningLabel } from "./learning";
import { familyLabel, STEP_FAMILIES, stepDescription, stepFamily } from "./steps";

const singleNames: Record<string, string> = {
  detector: "detector", calibration: "calibration step", policy: "detection rule", output: "output",
};
const listed = (names: string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

export function PipelineToolbox({
  components,
  document,
  link,
  choices,
  blocks = [],
  onAdd,
  onPlace,
  onSelect,
  onDragStart,
  onDragEnd,
}: {
  components: PipelineComponent[];
  document: GraphDocument;
  /** Inserting on this connection: only the steps that fit it are listed. */
  link?: Link;
  /** The steps to offer instead, such as the ones a feature's row can add. */
  choices?: PipelineComponent[];
  /** Saved blocks, listed below the steps with what adding each one here gives. */
  blocks?: BlockChoice[];
  onAdd: (componentId: string) => void;
  /** Takes the design a chosen block gives and the first of its steps. */
  onPlace?: (placed: { document: GraphDocument; id: string }) => void;
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
  const offered = choices ?? components.filter((component) =>
    (isMultiInstanceKind(component.kind) || !definition.nodes.some((node) => node.kind === component.kind))
    && (!link || !insertBlocker(definition, link, component, components)));
  const matches = offered.filter((component) =>
    `${component.label} ${stepDescription(component)} ${component.description} ${familyLabel(stepFamily(component.kind, component.id))}`
      .toLocaleLowerCase()
      .includes(search));
  const sections = STEP_FAMILIES
    .map((family) => ({ ...family, items: matches.filter((component) => stepFamily(component.kind, component.id) === family.id) }))
    .filter((section) => section.items.length);
  const offeredBlocks = blocks.filter(({ block, detail }) => `${block.name} ${detail} block`.toLocaleLowerCase().includes(search));
  // The detector, calibration step, detection rule and output are changed in their own settings, not added again.
  const present = link || choices ? [] : definition.nodes.filter((node) => node.kind in singleNames
    && (!search || `${nodeLabel(node, components, document.layout)} ${singleNames[node.kind]}`.toLocaleLowerCase().includes(search)));
  // Several detectors read as one entry: "the 2 detectors, policy and output".
  const kinds = [...new Set(present.map((node) => node.kind))];
  const presentText = listed(kinds.map((kind) => {
    const count = present.filter((node) => node.kind === kind).length;
    return count > 1 ? `${count} ${singleNames[kind]}s` : singleNames[kind]!;
  }));
  const full = definition.nodes.length >= PIPELINE_LIMITS.nodes;
  // Two steps can share a name and differ in how they learn; their names then say so.
  const shared = new Set(offered.map((component) => component.label)
    .filter((label, index, labels) => labels.indexOf(label) !== index));
  const named = (component: PipelineComponent) => shared.has(component.label) && learningLabel(component)
    ? `${component.label}, ${learningLabel(component)!.toLowerCase()}` : component.label;
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
            const block = first ? undefined : offeredBlocks.find((choice) => !blockedBy(choice.outcome))?.outcome;
            if (!first && !block) return;
            event.preventDefault();
            if (first) onAdd(first.id);
            else if (block && !("blocked" in block)) onPlace?.(block);
          }
        }}
      />
      {!choices && <p className="pl-toolbox-count" role="status">{definition.nodes.length} / {PIPELINE_LIMITS.nodes}</p>}
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
                  aria-label={`${link ? "Insert" : "Add"} ${named(component)}`}
                  aria-describedby={`${id}-${component.id}`}
                  disabled={!!reason}
                  draggable={!link && !choices && !reason}
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
                  {/* A step the deployment cannot run says why instead of what it does. */}
                  <small id={`${id}-${component.id}`}>{component.unavailable ?? stepDescription(component)}</small>
                  {learningLabel(component) && <small className="pl-learning-tag">{learningLabel(component)}</small>}
                </button>;
              })}
            </div>
          </section>
        ))}
        {offeredBlocks.length > 0 && <section aria-labelledby={`${id}-blocks`}>
          <h4 id={`${id}-blocks`}>Blocks</h4>
          <div className="pl-toolbox-grid">
            {offeredBlocks.map(({ block, detail, outcome }) => {
              const reason = blockedBy(outcome);
              return <button type="button" key={block.id} className="pl-toolbox-item" title={reason}
                aria-label={`${link ? "Insert" : "Add"} block ${block.name}`} aria-describedby={`${id}-block-${block.id}`}
                disabled={!!reason} onClick={() => { if (!("blocked" in outcome)) onPlace?.(outcome); }}>
                <strong>{block.name}</strong>
                <small id={`${id}-block-${block.id}`}>{reason ?? detail}</small>
              </button>;
            })}
          </div>
        </section>}
        {present.length > 0 && <div className="pl-toolbox-present">
          <p className="pl-help">
            The {presentText} {present.length === 1 ? "is" : "are"} already in this pipeline.
            {onSelect ? ` Open ${present.length === 1 ? "it" : "one"} to change it.` : ""}
            {present.some((node) => node.kind === "detector") ? " A detector's settings can add another detector." : ""}
          </p>
          {onSelect && <div>
            {present.map((node) => {
              const label = nodeLabel(node, components, document.layout);
              return <button type="button" key={node.id} aria-label={`Select ${label}`} onClick={() => onSelect(node.id)}>{label}</button>;
            })}
          </div>}
        </div>}
      </div>
      {!sections.length && !present.length && !offeredBlocks.length && <p className="pl-help">
        {link && !search ? "No step fits this connection." : "No matching steps."}
      </p>}
    </aside>
  );
}
