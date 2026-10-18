import { useState } from "react";
import type { PipelineCatalog, PipelineDefinition } from "./contracts";
import { canAddComponent } from "./model";
import { nodeKinds } from "./semantics";

export function PipelineToolbox({
  catalog,
  definition,
  onAdd,
  onDragStart,
  onDragEnd,
}: {
  catalog: PipelineCatalog;
  definition: PipelineDefinition;
  onAdd: (componentId: string) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}) {
  const [query, setQuery] = useState("");
  const components = catalog.components.filter(
    (component) =>
      canAddComponent(definition, component) &&
      `${component.label} ${component.description}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  return (
    <aside className="pl-toolbox" aria-label="Pipeline toolbox">
      <input
        type="search"
        aria-label="Search components"
        placeholder="Search components…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <p className="pl-toolbox-count" role="status">{definition.nodes.length} / 64</p>
      {(
        [
          "source",
          "transform",
          "merge",
          "detector",
          "policy",
          "output",
        ] as const
      ).filter((kind) => components.some((component) => component.kind === kind)).map((kind) => (
        <section key={kind}>
          <h4>{nodeKinds[kind]}</h4>
          {components
            .filter((component) => component.kind === kind)
            .map((component) => (
              <button
                type="button"
                key={component.id}
                className="pl-toolbox-item"
                title={component.description}
                aria-label={`Add ${component.label}`}
                draggable
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
              </button>
            ))}
        </section>
      ))}
      {!components.length && <p className="pl-help">{definition.nodes.length >= 64
        ? "Component limit reached." : "No matching components."}</p>}
    </aside>
  );
}
