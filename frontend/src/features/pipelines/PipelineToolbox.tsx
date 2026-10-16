import { useState } from "react";
import type { PipelineCatalog, PipelineDefinition } from "./contracts";

export function PipelineToolbox({
  catalog,
  definition,
  onAdd,
}: {
  catalog: PipelineCatalog;
  definition: PipelineDefinition;
  onAdd: (componentId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const components = catalog.components.filter(
    (component) =>
      component.strategies.includes(definition.strategy) &&
      `${component.label} ${component.description}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  return (
    <aside className="pl-toolbox" aria-label="Pipeline toolbox">
      <h3>Components</h3>
      <input
        type="search"
        aria-label="Search components"
        placeholder="Search components…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <p className="pl-help">
        Drag onto the canvas or choose Add. Connect components using the
        inspector or their handles.
      </p>
      <p className="pl-help" role="status">
        {definition.nodes.length} of 64 components
        {definition.nodes.length >= 64
          ? " · remove a component before adding another."
          : "."}
      </p>
      {(
        [
          "source",
          "transform",
          "merge",
          "detector",
          "policy",
          "output",
        ] as const
      ).map((kind) => (
        <section key={kind}>
          <h4>
            {kind === "transform"
              ? "Feature processing"
              : `${kind[0]!.toUpperCase()}${kind.slice(1)}`}
          </h4>
          {components
            .filter((component) => component.kind === kind)
            .map((component) => (
              <button
                type="button"
                key={component.id}
                className="pl-toolbox-item"
                title={component.description}
                aria-label={`Add ${component.label}`}
                draggable={
                  definition.nodes.length < 64 &&
                  (kind === "transform" ||
                    kind === "merge" ||
                    !definition.nodes.some((node) => node.kind === kind))
                }
                onDragStart={(event) => {
                  event.dataTransfer.setData(
                    "application/off-key-component",
                    component.id,
                  );
                  event.dataTransfer.effectAllowed = "copy";
                }}
                disabled={
                  definition.nodes.length >= 64 ||
                  (kind !== "transform" &&
                    kind !== "merge" &&
                    definition.nodes.some((node) => node.kind === kind))
                }
                onClick={() => onAdd(component.id)}
              >
                <span>{component.label}</span>
                <small>Add</small>
              </button>
            ))}
        </section>
      ))}
    </aside>
  );
}
