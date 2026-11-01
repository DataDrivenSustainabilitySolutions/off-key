import { useId, useState, type ReactNode } from "react";
import type { PipelineCatalog, PipelineValidation } from "./contracts";
import { ParameterFields } from "@/components/parameter-editor/ParameterFields";
import { hasParameterControl } from "@/components/parameter-editor/types";
import {
  connectNodes,
  connectionIssue,
  disconnectEdge,
  incomingEdges,
  moveMergeInput,
  nodeOptionLabeler,
  removeNode,
  replaceComponent,
  setNodeLabel,
  setNodeParams,
  type GraphDocument,
} from "./model";
import { componentFor, dataKinds, inputKind, outputKind } from "./semantics";
import type { HistoryMode } from "./types";

type Props = {
  document: GraphDocument;
  catalog: PipelineCatalog;
  selected?: string;
  validation?: PipelineValidation;
  readOnly?: boolean;
  header?: ReactNode;
  content?: ReactNode;
  /** Shown for the input instead of its generic settings: the readings it monitors. */
  input?: ReactNode;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
};

export function PipelineInspector({
  document,
  catalog,
  selected,
  validation,
  readOnly,
  header,
  content,
  input: inputContent,
  onSelect,
  onChange,
}: Props) {
  const connectionHelpId = useId();
  const [modelQuery, setModelQuery] = useState("");
  const node = document.definition.nodes.find((item) => item.id === selected);
  const component = componentFor(node, catalog.components);
  const incoming = selected ? incomingEdges(document.definition, selected) : [];
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
  const optionLabel = nodeOptionLabeler(document, catalog.components);
  const featureLabels = Object.fromEntries(
    document.definition.input_slots.map((slot) => [
      slot.id,
      slot.label === slot.id ? slot.id : `${slot.label} · ${slot.id}`,
    ]),
  );
  const lineage = node && validation?.features[node.id] && (
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
          step.
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
  );
  const titleField = node && (
    <label className="pl-field">
      <span>Step title</span>
      <input
        maxLength={120}
        value={document.layout.nodes[node.id]?.label ?? ""}
        placeholder={component?.label ?? node.component}
        disabled={readOnly}
        onChange={(event) =>
          onChange(setNodeLabel(document, node.id, event.target.value), `title:${node.id}`)
        }
      />
    </label>
  );
  const nodeIssues = node && validation?.issues
    .filter((issue) => issue.node_id === node.id && !hasParameterControl(component?.fields ?? [], issue.parameter_path))
    .map((issue, index) => (
      <p key={index} className="pl-error" role="alert">
        {issue.message}
      </p>
    ));
  return (
    <aside className="pl-inspector" aria-label={header ? "Monitoring inspector" : "Component inspector"}>
      {header}
      {content ?? <>
      <label className="pl-field">
        <span>Selected step</span>
        <select
          value={selected ?? ""}
          onChange={(event) => onSelect(event.target.value || undefined)}
        >
          <option value="">Choose a step</option>
          {document.definition.nodes.map((item) => (
            <option key={item.id} value={item.id}>
              {optionLabel(item)}
            </option>
          ))}
        </select>
      </label>
      {node && node.kind === "source" && inputContent ? (
        <>
          <h3>Input</h3>
          {inputContent}
          {titleField}
          {lineage}
          {nodeIssues}
        </>
      ) : node ? (
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
          {node.kind === "detector" && (() => {
            const query = modelQuery.trim().toLocaleLowerCase();
            const models = catalog.components
              .filter(
                (item) =>
                  item.kind === "detector" &&
                  item.strategies.includes(document.definition.strategy) &&
                  (item.id === node.component ||
                    `${item.label} ${item.description}`.toLocaleLowerCase().includes(query)),
              )
              .sort((left, right) => left.label.localeCompare(right.label));
            return (
              <div className="pl-field">
                <label htmlFor={`${node.id}-detector-model`}>Detector model</label>
                {!readOnly && (
                  <input
                    type="search"
                    aria-label="Filter detector models"
                    placeholder="Filter models…"
                    value={modelQuery}
                    onChange={(event) => setModelQuery(event.target.value)}
                  />
                )}
                <select
                  id={`${node.id}-detector-model`}
                  aria-label="Detector model"
                  value={node.component}
                  disabled={readOnly}
                  onChange={(event) => {
                    const replacement = catalog.components.find(
                      (item) => item.id === event.target.value,
                    );
                    if (replacement) onChange(replaceComponent(document, node.id, replacement));
                  }}
                >
                  {models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <small className="pl-help">
                  {query && models.length <= 1
                    ? "No other model matches this filter. "
                    : ""}
                  Changing the model resets its parameters to catalog defaults.
                  Connections are retained.
                </small>
              </div>
            );
          })()}
          {titleField}
          {component && (
            <ParameterFields
              fields={component.fields}
              issues={(validation?.issues ?? []).filter(issue => issue.node_id === node.id && issue.parameter_path != null).map(issue => ({ path: issue.parameter_path!, message: issue.message }))}
              values={node.params}
              features={features}
              featureLabels={featureLabels}
              prefix={node.id}
              readOnly={readOnly}
              onChange={(params) => {
                const changed = Object.keys(params)
                  .filter((key) => params[key] !== node.params[key])
                  .sort()
                  .join(",");
                onChange(setNodeParams(document, node.id, params), `param:${node.id}:${changed}`);
              }}
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
                  {optionLabel(
                    document.definition.nodes.find(
                      (item) => item.id === edge.source,
                    ),
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
                        onChange({ ...document, definition: disconnectEdge(document.definition, edge) })
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
                  <option value="">Choose upstream step</option>
                  {candidates.map((item) => (
                    <option key={item.id} value={item.id}>
                      {optionLabel(item)}
                    </option>
                  ))}
                </select>
                <small className="pl-help" id={connectionHelpId}>
                  {candidates.length
                    ? "Only compatible, cycle-free connections are listed."
                    : "No compatible upstream output is available. Add a step or disconnect an occupied input."}
                </small>
              </label>
            )}
          {lineage}
          {nodeIssues}
          {!readOnly && (
            <button
              type="button"
              className="pl-danger"
              onClick={() => onChange(removeNode(document, node.id))}
            >
              Remove step
            </button>
          )}
        </>
      ) : (
        <p className="pl-help">Select a step.</p>
      )}
      </>}
    </aside>
  );
}
