import { useId, type ReactNode } from "react";
import type { PipelineCatalog, PipelineValidation } from "./contracts";
import { ParameterFields } from "./ParameterFields";
import {
  connectNodes,
  connectionIssue,
  moveMergeInput,
  nodeOptionLabel,
  removeNode,
  type GraphDocument,
} from "./model";
import { componentFor, dataKinds, inputKind, outputKind } from "./semantics";

type Props = {
  document: GraphDocument;
  catalog: PipelineCatalog;
  selected?: string;
  validation?: PipelineValidation;
  readOnly?: boolean;
  header?: ReactNode;
  content?: ReactNode;
  onSelect: (id: string) => void;
  onChange: (document: GraphDocument) => void;
};

export function PipelineInspector({
  document,
  catalog,
  selected,
  validation,
  readOnly,
  header,
  content,
  onSelect,
  onChange,
}: Props) {
  const connectionHelpId = useId();
  const node = document.definition.nodes.find((item) => item.id === selected);
  const component = componentFor(node, catalog.components);
  const incoming = document.definition.edges
    .filter((edge) => edge.target === selected)
    .sort((left, right) => left.order - right.order);
  const features = [
    ...new Set(
      incoming.flatMap(
        (edge) =>
          validation?.features[edge.source]?.map((feature) => feature.name) ??
          [],
      ),
    ),
  ];
  const input = inputKind(component);
  const output = node ? outputKind(node, component) : undefined;
  const candidates = node
    ? document.definition.nodes.filter(
        (item) =>
          !connectionIssue(
            document.definition,
            item.id,
            node.id,
            catalog.components,
          ),
      )
    : [];
  const featureLabels = Object.fromEntries(
    document.definition.input_slots.map((slot) => [
      slot.id,
      slot.label === slot.id ? slot.id : `${slot.label} · ${slot.id}`,
    ]),
  );
  return (
    <aside className="pl-inspector" aria-label={header ? "Monitoring inspector" : "Component inspector"}>
      {header}
      {content ?? <>
      <label className="pl-field">
        <span>Selected component</span>
        <select
          value={selected ?? ""}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="">Choose component</option>
          {document.definition.nodes.map((item) => (
            <option key={item.id} value={item.id}>
              {nodeOptionLabel(item, document, catalog.components)}
            </option>
          ))}
        </select>
      </label>
      {node ? (
        <>
          <h3>{component?.label ?? node.component}</h3>
          {component?.description && (
            <p className="pl-help">{component.description}</p>
          )}
          {component && (
            <p className="pl-help pl-inspector-signature">
              {input ? `${dataKinds[input].label} → ` : ""}
              {output ? dataKinds[output].label : "Stored evidence and alarms"}
            </p>
          )}
          {node.kind === "detector" && (
            <label className="pl-field">
              <span>Detector model</span>
              <select
                aria-label="Detector model"
                value={node.component}
                disabled={readOnly}
                onChange={(event) => {
                  const replacement = catalog.components.find(
                    (item) => item.id === event.target.value,
                  );
                  if (!replacement) return;
                  const params = Object.fromEntries(
                    replacement.fields
                      .filter((field) => field.default !== undefined)
                      .map((field) => [field.name, field.default!]),
                  );
                  onChange({
                    ...document,
                    definition: {
                      ...document.definition,
                      nodes: document.definition.nodes.map((item) =>
                        item.id === node.id
                          ? {
                              ...item,
                              component: replacement.id,
                              contract_version:
                                replacement.contract_version ?? 1,
                              params,
                            }
                          : item,
                      ),
                    },
                  });
                }}
              >
                {catalog.components
                  .filter(
                    (item) =>
                      item.kind === "detector" &&
                      item.strategies.includes(document.definition.strategy),
                  )
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
              </select>
              <small className="pl-help">
                Changing the model resets its parameters to catalog defaults.
                Connections are retained.
              </small>
            </label>
          )}
          <label className="pl-field">
            <span>Node title</span>
            <input
              maxLength={120}
              value={document.layout.nodes[node.id]?.label ?? ""}
              placeholder={component?.label ?? node.component}
              disabled={readOnly}
              onChange={(event) =>
                onChange({
                  ...document,
                  layout: {
                    ...document.layout,
                    nodes: {
                      ...document.layout.nodes,
                      [node.id]: {
                        x: 0,
                        y: 0,
                        ...document.layout.nodes[node.id],
                        label: event.target.value,
                      },
                    },
                  },
                })
              }
            />
          </label>
          {component && (
            <ParameterFields
              fields={component.fields}
              values={node.params}
              features={features}
              featureLabels={featureLabels}
              prefix={node.id}
              readOnly={readOnly}
              onChange={(params) =>
                onChange({
                  ...document,
                  definition: {
                    ...document.definition,
                    nodes: document.definition.nodes.map((item) =>
                      item.id === node.id ? { ...item, params } : item,
                    ),
                  },
                })
              }
            />
          )}
          <h4>
            Incoming connections{node.kind === "merge" ? " · output order" : ""}
          </h4>
          {node.kind === "merge" && (
            <p className="pl-help">
              Combine feature columns from the same aligned observation, in the
              order below.
            </p>
          )}
          <ol className="pl-connections">
            {incoming.map((edge, index) => (
              <li key={edge.source}>
                <span>
                  {node.kind === "merge" && <small>Input {index + 1} · </small>}
                  {nodeOptionLabel(
                    document.definition.nodes.find(
                      (item) => item.id === edge.source,
                    ),
                    document,
                    catalog.components,
                  )}
                </span>
                {!readOnly && (
                  <div>
                    {node.kind === "merge" && (
                      <>
                        <button
                          type="button"
                          disabled={index === 0}
                          aria-label={`Move input ${index + 1} earlier`}
                          onClick={() =>
                            onChange({
                              ...document,
                              definition: moveMergeInput(
                                document.definition,
                                node.id,
                                index,
                                -1,
                              ),
                            })
                          }
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          disabled={index === incoming.length - 1}
                          aria-label={`Move input ${index + 1} later`}
                          onClick={() =>
                            onChange({
                              ...document,
                              definition: moveMergeInput(
                                document.definition,
                                node.id,
                                index,
                                1,
                              ),
                            })
                          }
                        >
                          ↓
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      aria-label={`Disconnect ${edge.source} from ${node.id}`}
                      onClick={() =>
                        onChange({
                          ...document,
                          definition: {
                            ...document.definition,
                            edges: document.definition.edges.filter(
                              (item) => item !== edge,
                            ),
                          },
                        })
                      }
                    >
                      ×
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!incoming.length && (
            <p className="pl-help">
              {node.kind === "source"
                ? "Aligned catalogue readings enter here."
                : "No input connected."}
            </p>
          )}
          {!readOnly &&
            node.kind !== "source" &&
            (node.kind === "merge" || !incoming.length) && (
              <label className="pl-field">
                <span>Connect input from</span>
                <select
                  aria-label="Connect input from"
                  aria-describedby={connectionHelpId}
                  value=""
                  onChange={(event) => {
                    onChange({
                      ...document,
                      definition: connectNodes(
                        document.definition,
                        event.target.value,
                        node.id,
                        catalog.components,
                      ),
                    });
                  }}
                >
                  <option value="">Choose upstream component</option>
                  {candidates.map((item) => (
                    <option key={item.id} value={item.id}>
                      {nodeOptionLabel(item, document, catalog.components)}
                    </option>
                  ))}
                </select>
                <small className="pl-help" id={connectionHelpId}>
                  {candidates.length
                    ? "Only compatible, cycle-free connections are listed."
                    : "No compatible upstream output is available. Add a component or disconnect an occupied input."}
                </small>
              </label>
            )}
          {validation?.features[node.id] && (
            <>
              <h4>
                {component?.output_type === "features" ||
                ["source", "transform", "merge"].includes(node.kind)
                  ? "Output features"
                  : "Contributing feature lineage"}
              </h4>
              {validation.provenance_complete === false && (
                <p className="pl-help">
                  Some source provenance is omitted to keep this inspection
                  bounded. Feature names and order remain complete for this
                  component.
                </p>
              )}
              <ul className="pl-lineage">
                {validation.features[node.id]?.map((feature) => (
                  <li key={feature.name}>
                    <strong>
                      {featureLabels[feature.name] ?? feature.name}
                    </strong>
                    <small>
                      {feature.slots.length ? (
                        <>
                          From{" "}
                          {feature.slots
                            .map((slot) => featureLabels[slot] ?? slot)
                            .join(", ")}
                        </>
                      ) : validation.provenance_complete === false ? (
                        "Source provenance omitted"
                      ) : (
                        "Source provenance unavailable"
                      )}
                    </small>
                  </li>
                ))}
              </ul>
            </>
          )}
          {validation?.issues
            .filter((issue) => issue.node_id === node.id)
            .map((issue, index) => (
              <p key={index} className="pl-error" role="alert">
                {issue.message}
              </p>
            ))}
          {!readOnly && (
            <button
              type="button"
              className="pl-danger"
              onClick={() => onChange(removeNode(document, node.id))}
            >
              Remove component
            </button>
          )}
        </>
      ) : (
        <p className="pl-help">Select a component.</p>
      )}
      </>}
    </aside>
  );
}
