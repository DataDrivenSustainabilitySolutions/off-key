import { useId, useState, type ReactNode } from "react";
import type { PipelineCatalog, PipelineComponent, PipelineNode, PipelineValidation } from "./contracts";
import { ParameterFields } from "@/components/parameter-editor/ParameterFields";
import { hasParameterControl } from "@/components/parameter-editor/types";
import {
  addDetector,
  connectNodes,
  connectionIssue,
  detectorBlocker,
  detectorIds,
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
import { afterGate, featureBlocker, rangeText, readyText } from "./features";
import {
  calibrationFamily, changeCalibration, changeDetector, changeNotice, coverage, FIXED_SPLIT, fittingPolicy,
  learningLabel, type Learning, UNTRAINED,
} from "./learning";
import { usesForecastService, type ForecastModels } from "./forecastModels";
import { PipelineForecastModels } from "./PipelineForecastModels";
import { PipelineFormula } from "./PipelineFormula";
import { PipelineApart, PipelineScope } from "./PipelineScope";
import { PipelineTime } from "./PipelineTime";
import { apartField, combinedName, hasScope, isWarning } from "./scope";
import { componentFor, dataKinds, inputKind, outputKind } from "./semantics";
import { CONDITION_STEPS, FORMULA_STEPS, FUSION_CHOICES, fusionChoice, stepFields } from "./steps";
import type { HistoryMode } from "./types";

/** Detector models by how they learn, in the order the picker lists them. */
const LEARNING_GROUPS: { mode: Learning; label: string }[] = [
  { mode: "online", label: "Learns continuously" },
  { mode: "batch", label: "Fitted once" },
  { mode: "pretrained", label: "Pretrained" },
  { mode: "none", label: UNTRAINED },
];

type Props = {
  document: GraphDocument;
  catalog: PipelineCatalog;
  selected?: string;
  validation?: PipelineValidation;
  /** The latest report while an edit is being checked; its features stay listed meanwhile. */
  lastValidation?: PipelineValidation;
  readOnly?: boolean;
  header?: ReactNode;
  content?: ReactNode;
  /** Shown for the input instead of its generic settings: the readings it monitors. */
  input?: ReactNode;
  /** What the forecast service holds, for the steps whose model lives there. */
  forecast?: ForecastModels;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
};

export function PipelineInspector({
  document,
  catalog,
  selected,
  validation,
  lastValidation,
  readOnly,
  header,
  content,
  input: inputContent,
  forecast,
  onSelect,
  onChange,
}: Props) {
  const connectionHelpId = useId();
  const [modelQuery, setModelQuery] = useState("");
  // What a change of model or method did besides the step itself, until the next change.
  const [notice, setNotice] = useState<{ node: string; component: string; text: string }>();
  const node = document.definition.nodes.find((item) => item.id === selected);
  const component = componentFor(node, catalog.components);
  const incoming = selected ? incomingEdges(document.definition, selected) : [];
  // Feature lists keep the latest report while an edit is checked, so choices do not jump.
  const report = validation ?? lastValidation;
  const features = [
    ...new Set(
      incoming.flatMap(
        (edge) =>
          report?.features[edge.source]?.map((feature) => feature.name) ??
          [],
      ),
    ),
  ];
  // Features that follow one reading; a Formula for each feature starts with these.
  const readings = [
    ...new Set(
      incoming.flatMap(
        (edge) =>
          report?.features[edge.source]
            ?.filter((feature) => feature.slots?.length === 1)
            .map((feature) => feature.name) ?? [],
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
  // When the features that arrive are unknown, the step whose problem hides them.
  const blocker = node ? featureBlocker(document.definition, report, node.id) : undefined;
  const blockerNode = document.definition.nodes.find((item) => item.id === blocker?.node);
  // The problem with the setting it is on, such as "a problem with Mapping: Enter a value."
  const blockerField = blocker?.issue?.parameter_path?.length
    ? componentFor(blockerNode, catalog.components)?.fields.find((field) => field.name === blocker.issue!.parameter_path![0])
    : undefined;
  const blockerMessage = blocker?.issue && `${blockerField ? ` with ${blockerField.label}` : ""}: ${blocker.issue.message}`;
  const featureHint = !incoming.length ? undefined : !report
    ? <p className="pl-help">Checking which features arrive here…</p>
    : blocker && <p className="pl-warning" role="status">
      {blockerNode
        ? <>The features arriving here aren't known yet, because {optionLabel(blockerNode)} has a
          problem{blockerMessage}
          <button type="button" className="pl-formula-fix" onClick={() => onSelect(blockerNode.id)}>
            Go to {optionLabel(blockerNode)}
          </button></>
        : "The features arriving here aren't known yet. Fix the problems marked on the steps before this one."}
    </p>;
  const featureLabels = Object.fromEntries(
    document.definition.input_slots.map((slot) => [
      slot.id,
      slot.label === slot.id ? slot.id : `${slot.label} · ${slot.id}`,
    ]),
  );
  const lineage = node && report?.features[node.id] && (
    <>
      <h4>
        {component?.output_type === "features" ||
        ["source", "transform", "merge"].includes(node.kind)
          ? "Output features"
          : "Contributing feature lineage"}
      </h4>
      {report.provenance_complete === false && (
        <p className="pl-help">
          Some source provenance is omitted to keep this inspection
          bounded. Feature names and order remain complete for this
          step.
        </p>
      )}
      <ul className="pl-lineage">
        {report.features[node.id]?.map((feature) => {
          const range = rangeText(feature.minimum, feature.maximum);
          return <li key={feature.name}>
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
              ) : report.provenance_complete === false ? (
                "Source provenance omitted"
              ) : (
                "From no reading"
              )}
              {range && ` · ${range}`}
            </small>
          </li>;
        })}
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
  // Errors on a setting appear beside it; warnings never block and are listed here.
  const nodeIssues = node && validation?.issues
    .filter((issue) => issue.node_id === node.id
      && (isWarning(issue) || !hasParameterControl(component?.fields ?? [], issue.parameter_path)))
    .map((issue, index) => isWarning(issue)
      ? <p key={index} className="pl-warning" role="status">{issue.message}</p>
      : <p key={index} className="pl-error" role="alert">{issue.message}</p>);
  const fieldIssues = (validation?.issues ?? [])
    .filter((issue) => node && issue.node_id === node.id && issue.parameter_path != null && !isWarning(issue))
    .map((issue) => ({ path: issue.parameter_path!, message: issue.message, fix: issue.fix }));
  // When the step first has output, for the steps of the Prepare stage.
  const ready = node && report?.ready_after?.[node.id];
  const computed = node && report?.features[node.id]?.find((feature) => feature.name === combinedName(node, component));
  const scoped = hasScope(component);
  // The feature a Rolling relation compares with or an Expected value expects.
  const apart = node && apartField(node.component);
  const changeParams = (params: PipelineNode["params"], changed: string) => {
    if (node) onChange(setNodeParams(document, node.id, params), `param:${node.id}:${changed}`);
  };
  const detectors = detectorIds(document.definition);
  /** Swap the step's component and show what else followed from it. */
  const swap = (replacement: PipelineComponent) => {
    if (!node) return;
    const change = node.kind === "detector"
      ? changeDetector(document.definition, node.id, replacement, catalog.components)
      : node.kind === "calibration"
        ? changeCalibration(document.definition, node.id, replacement, catalog.components)
        : { definition: replaceComponent(document, node.id, replacement).definition, converted: [] };
    const text = changeNotice(change, replacement.learning);
    setNotice(text ? { node: node.id, component: replacement.id, text } : undefined);
    onChange({ ...document, definition: change.definition });
  };
  const swapNotice = node && notice?.node === node.id && notice.component === node.component
    ? <p className="pl-notice" role="status">{notice.text}</p> : null;
  const fitting = fittingPolicy(document.definition, catalog.components);
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
          {ready ? <p className="pl-help pl-ready">{readyText(ready, afterGate(document.definition, node.id))}</p> : null}
          {node.kind === "detector" && (() => {
            const query = modelQuery.trim().toLocaleLowerCase();
            const models = catalog.components
              .filter(
                (item) =>
                  item.kind === "detector" &&
                  (item.id === node.component ||
                    `${item.label} ${item.description} ${learningLabel(item) ?? ""}`.toLocaleLowerCase().includes(query)),
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
                    if (replacement) swap(replacement);
                  }}
                >
                  {LEARNING_GROUPS.map((group) => {
                    const items = models.filter((item) => (item.learning ?? "none") === group.mode);
                    return items.length ? <optgroup key={group.mode} label={group.label}>
                      {items.map((item) => <option key={item.id} value={item.id}
                        disabled={!!item.unavailable && item.id !== node.component}>
                        {item.label}{item.unavailable ? " (no forecast service)" : ""}
                      </option>)}
                    </optgroup> : null;
                  })}
                </select>
                <small className="pl-help">
                  {query && models.length <= 1
                    ? "No other model matches this filter. "
                    : ""}
                  {learningLabel(component) ? `${learningLabel(component)}. ` : ""}
                  Changing the model resets its parameters to catalog defaults.
                  Connections are retained. A model that learns differently takes
                  the learned steps before it and the detection rule along.
                </small>
                {swapNotice}
              </div>
            );
          })()}
          {node.kind === "calibration" && (() => {
            const methods = catalog.components.filter((item) => item.kind === "calibration");
            const groups = [...new Set(methods.map(calibrationFamily))];
            const promise = coverage(component);
            return (
              <div className="pl-field">
                <label htmlFor={`${node.id}-calibration-method`}>Calibration method</label>
                <select
                  id={`${node.id}-calibration-method`}
                  aria-label="Calibration method"
                  value={node.component}
                  disabled={readOnly}
                  onChange={(event) => {
                    const replacement = methods.find((item) => item.id === event.target.value);
                    if (replacement) swap(replacement);
                  }}
                >
                  {groups.map((group) => <optgroup key={group} label={group}>
                    {methods.filter((item) => calibrationFamily(item) === group)
                      .map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                  </optgroup>)}
                </select>
                {promise && <small className={`pl-help pl-coverage is-${component!.coverage}`}>
                  <strong>{promise.label}.</strong> {promise.help}
                </small>}
                {component?.reference && <small className="pl-help">{component.reference}</small>}
                <small className="pl-help">
                  {node.component === FIXED_SPLIT
                    ? "The calibration window stays as it is. Methods that adapt keep moving their boundary and alarm by the exceedance rule."
                    : "The boundary keeps adapting. The fixed split freezes the calibration window instead."}
                  {" "}The detection rule follows the method.
                </small>
                {swapNotice}
              </div>
            );
          })()}
          {node.kind === "policy" && (() => {
            const rules = catalog.components.filter((item) => item.kind === "policy");
            return (
              <div className="pl-field">
                <label htmlFor={`${node.id}-detection-rule`}>Detection rule</label>
                <select
                  id={`${node.id}-detection-rule`}
                  aria-label="Detection rule"
                  value={node.component}
                  disabled={readOnly}
                  onChange={(event) => {
                    const replacement = rules.find((item) => item.id === event.target.value);
                    if (replacement) swap(replacement);
                  }}
                >
                  {rules.map((item) => <option key={item.id} value={item.id}>
                    {item.label}{fitting && item.id !== fitting ? " (does not fit this design)" : ""}
                  </option>)}
                </select>
                <small className="pl-help">
                  The calibration step and how the detectors learn decide which rule fits.
                  {fitting && node.component !== fitting
                    ? ` This design needs ${rules.find((item) => item.id === fitting)?.label ?? "another rule"}.` : ""}
                </small>
              </div>
            );
          })()}
          {node.kind === "detector" && !readOnly && (() => {
            const blocked = detectorBlocker(document.definition);
            return (
              <div className="pl-field">
                <button
                  type="button"
                  disabled={!!blocked}
                  onClick={() => {
                    const added = addDetector(document, node.id);
                    if (!added) return;
                    onChange(added.document);
                    onSelect(added.id);
                  }}
                >
                  Add another detector
                </button>
                <small className="pl-help">
                  {blocked ?? "Adds a detector like this one that reads the same features. The calibration step combines them; change its model or input afterwards."}
                </small>
              </div>
            );
          })()}
          {node.kind === "calibration" && detectors.length > 1 && (
            <div className="pl-field">
              <span id={`${node.id}-fusion`}>Combine detectors</span>
              <div className="pl-segmented" role="group" aria-labelledby={`${node.id}-fusion`}>
                {FUSION_CHOICES.map((choice) => (
                  <button
                    key={choice.value}
                    type="button"
                    disabled={readOnly}
                    aria-pressed={fusionChoice(node).value === choice.value}
                    onClick={() => changeParams({ ...node.params, fusion: choice.value }, "fusion")}
                  >
                    {choice.label}
                  </button>
                ))}
              </div>
              <small className="pl-help">
                {fusionChoice(node).help} Each score counts by its rank against that
                detector's own calibration scores.
              </small>
            </div>
          )}
          {titleField}
          {component && apart && (
            <PipelineApart field={apart} node={node} features={features} featureLabels={featureLabels}
              featureHint={featureHint} issues={fieldIssues} readOnly={readOnly} onChange={changeParams} />
          )}
          {component && node.component === "prepare.time" && (
            <PipelineTime node={node} component={component} issues={fieldIssues} readOnly={readOnly} onChange={changeParams} />
          )}
          {component && scoped && (
            // The feature a step sets apart is never among the ones it uses.
            <PipelineScope node={node} component={component}
              features={features.filter((feature) => !apart || feature !== node.params[apart])}
              featureLabels={featureLabels}
              featureHint={featureHint} issues={fieldIssues} readOnly={readOnly} onChange={changeParams} />
          )}
          {component && FORMULA_STEPS.has(node.component) && (
            <PipelineFormula node={node} component={component} features={features} featureLabels={featureLabels}
              readings={readings} featureHint={featureHint} issues={fieldIssues} readOnly={readOnly} onChange={changeParams}
              range={computed ? rangeText(computed.minimum, computed.maximum) ?? "any value" : undefined} />
          )}
          {component && (
            <ParameterFields
              fields={stepFields(node, component)}
              issues={fieldIssues}
              values={node.params}
              features={features}
              featureLabels={featureLabels}
              featureHint={featureHint}
              prefix={node.id}
              readOnly={readOnly}
              onChange={(params) => changeParams(params, Object.keys(params)
                .filter((key) => params[key] !== node.params[key])
                .sort()
                .join(","))}
            />
          )}
          {component && CONDITION_STEPS.has(node.component) && (
            <PipelineFormula node={node} component={component} features={features} featureLabels={featureLabels}
              featureHint={featureHint} issues={fieldIssues} readOnly={readOnly} onChange={changeParams} />
          )}
          {component && forecast && usesForecastService(node.component) && (
            <PipelineForecastModels node={node} component={component} forecast={forecast} />
          )}
          <h4>
            {node.kind === "calibration" && detectors.length > 1
              ? "Detectors"
              : `Incoming connections${node.kind === "merge" ? " · output order" : ""}`}
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
            (node.kind === "merge" || !incoming.length || (node.kind === "calibration" && candidates.length > 0)) && (
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
