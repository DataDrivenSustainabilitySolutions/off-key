import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Plus, X } from "lucide-react";
import type { PipelineComponent, PipelineValidation } from "./contracts";
import { addForFeature, detectorsAfter, featuresView, rangeText, rowPlacement, rowSteps, type FeatureRow } from "./features";
import { nodeLabel, nodeOptionLabeler, type GraphDocument } from "./model";
import { PipelineToolbox } from "./PipelineToolbox";
import { componentFor } from "./semantics";
import { stepFamily } from "./steps";
import { nodeSummary } from "./summaries";

type Props = {
  document: GraphDocument;
  components: PipelineComponent[];
  /** The latest check of the graph; the view is computed from it and the graph. */
  report?: PipelineValidation;
  /** The report predates the latest edit and is being checked again. */
  stale?: boolean;
  selected?: string;
  readOnly?: boolean;
  onSelect: (id?: string) => void;
  onChange: (document: GraphDocument) => void;
};

const listed = (names: string[]) => names.length < 3
  ? names.join(" and ")
  : names.length === 3 ? `${names[0]}, ${names[1]} and ${names[2]}` : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;

/** The add-step menu of one feature's row: steps that use only that feature. */
function AddForFeature({ row, document, components, report, view, disabled, onAdded }: {
  row: FeatureRow;
  document: GraphDocument;
  components: PipelineComponent[];
  report: PipelineValidation;
  view: ReturnType<typeof featuresView>;
  disabled?: boolean;
  onAdded: (document: GraphDocument, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const steps = rowSteps(document.definition, components);
  const placed = (component: PipelineComponent) => rowPlacement(document.definition, report, view, row, component);
  const choices = steps.filter((component) => !("reason" in placed(component)));
  const refused = steps.map(placed).find((placement) => "reason" in placement);
  // A Prepare step runs before anything learns, so it can sit on a path other detectors share.
  const prepare = choices.find((component) => stepFamily(component.kind, component.id) === "prepare");
  const placement = prepare && placed(prepare);
  const label = nodeOptionLabeler(document, components);
  const node = (id: string) => document.definition.nodes.find((item) => item.id === id);
  const others = placement && "link" in placement
    ? detectorsAfter(document.definition, placement.link.target).filter((id) => id !== view.detector) : [];
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <Popover.Trigger className="pl-feature-add" aria-label={`Add a step for ${row.name}`} disabled={disabled}
      title={disabled ? "Waiting for the latest check" : `Add a step for ${row.name}`}>
      <Plus size={14} aria-hidden="true" />
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content className="pl-library pl-component-menu" align="start" sideOffset={6} collisionPadding={12}
        aria-label={`Add a step for ${row.name}`}
        onOpenAutoFocus={(event) => {
          const search = (event.currentTarget as HTMLElement).querySelector<HTMLInputElement>("input[type='search']");
          if (!search) return;
          event.preventDefault();
          search.focus();
        }}>
        <div className="pl-component-menu-heading">
          <h3>Add a step for <code>{row.name}</code></h3>
          <Popover.Close aria-label="Close steps"><X size={16} aria-hidden="true" /></Popover.Close>
        </div>
        {refused && "reason" in refused && <p className="pl-help">{refused.reason}</p>}
        {placement && "link" in placement && others.length > 0 && <p className="pl-help">
          Prepare steps go before {label(node(placement.link.target))}, so they also change what{" "}
          {listed(others.map((id) => label(node(id))))} {others.length === 1 ? "receives" : "receive"}.
        </p>}
        <PipelineToolbox components={components} document={document} choices={choices} onAdd={(id) => {
          const component = components.find((item) => item.id === id);
          const added = component && addForFeature(document, report, components, view, row, component);
          setOpen(false);
          if (added) onAdded(added.document, added.id);
        }} />
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}

/** One row per feature the detector receives: the steps that make it and its name there.
 * It is computed from the graph and its last check, so it always agrees with the graph. */
export function PipelineFeatures({ document, components, report, stale, selected, readOnly, onSelect, onChange }: Props) {
  const { definition, layout } = document;
  // A detector selected when the view opens is the one it shows first.
  const [chosen, setChosen] = useState(() =>
    definition.nodes.find((node) => node.id === selected && node.kind === "detector")?.id);
  const view = featuresView(definition, report, chosen);
  const optionLabel = nodeOptionLabeler(document, components);
  const labels = new Map(definition.input_slots.map((slot) => [slot.id, slot.label || slot.id]));
  const label = (slot: string) => labels.get(slot) ?? slot;
  const gates = definition.nodes.filter((node) => node.component === "prepare.gate");
  const readings = view.rows.filter((row) => row.reading !== undefined);
  const derived = view.rows.filter((row) => row.reading === undefined);
  const chip = (id: string) => {
    const node = definition.nodes.find((item) => item.id === id);
    if (!node) return null;
    const component = componentFor(node, components);
    const summary = nodeSummary(node, component, definition);
    return <button type="button" key={id} className={`pl-feature-step${selected === id ? " is-selected" : ""}`}
      data-family={stepFamily(node.kind, node.component)} aria-current={selected === id ? "true" : undefined}
      title={summary.text} onClick={() => onSelect(id)}>
      {nodeLabel(node, components, layout)}
    </button>;
  };
  const rowItem = (row: FeatureRow) => {
    const range = rangeText(row.minimum, row.maximum);
    return <li key={row.name} className="pl-feature-row">
      <span className="pl-feature-from">
        {row.reading !== undefined ? label(row.reading) : `From ${listed(row.slots.map(label))}`}
      </span>
      <span className="pl-feature-steps">
        {row.steps.map(chip)}
        {!row.steps.length && <span className="pl-feature-raw">{row.reading !== undefined ? "Raw" : ""}</span>}
        {!readOnly && report && <AddForFeature row={row} document={document} components={components} report={report}
          view={view} disabled={stale} onAdded={(next, id) => { onChange(next); onSelect(id); }} />}
      </span>
      <span className="pl-feature-name">
        <code>{row.name}</code>
        {range && <small>{range}</small>}
      </span>
    </li>;
  };
  const message = !report
    ? "The features appear once the graph has been checked."
    : !view.last ? "Connect a step to the detector to see the features it receives."
      : !report.features[view.last] ? "Resolve the issues before the detector to see the features it receives."
        : undefined;
  return <section className={`pl-features-view${stale ? " is-stale" : ""}`} aria-label="Features"
    aria-busy={stale || undefined}>
    <div className="pl-features-heading">
      <h3>Features the detector receives{view.rows.length ? <span>{view.rows.length}</span> : null}</h3>
      {gates.length > 0 && <div className="pl-feature-gates" role="group" aria-label="Gates">
        {gates.map((node) => <button type="button" key={node.id}
          className={`pl-feature-step${selected === node.id ? " is-selected" : ""}`} data-family="route"
          aria-current={selected === node.id ? "true" : undefined} onClick={() => onSelect(node.id)}>
          {nodeSummary(node, componentFor(node, components), definition).text ?? nodeLabel(node, components, layout)}
        </button>)}
      </div>}
    </div>
    {view.detectors.length > 1 && <div className="pl-features-detectors" role="group" aria-label="Detector">
      {view.detectors.map((id) => <button type="button" key={id} aria-pressed={view.detector === id}
        onClick={() => setChosen(id)}>
        {optionLabel(definition.nodes.find((node) => node.id === id))}
      </button>)}
    </div>}
    {stale && <p className="pl-help" role="status">Checking the latest changes…</p>}
    {message ? <p className="pl-help pl-features-empty">{message}</p> : <>
      {!view.complete && <p className="pl-help">
        This design is too large to list each feature's steps. Its names and order are complete.
      </p>}
      <div className="pl-feature-columns" aria-hidden="true">
        <span>From</span><span>Steps</span><span>Detector input</span>
      </div>
      {readings.length > 0 && <ol className="pl-features-list" aria-label="Features from readings">
        {readings.map(rowItem)}
      </ol>}
      {derived.length > 0 && <>
        <h4 className="pl-features-group">Made from several features</h4>
        <ol className="pl-features-list" aria-label="Features made from several">{derived.map(rowItem)}</ol>
      </>}
      {view.unused.length > 0 && <p className="pl-help">
        Not used by the detector: {listed(view.unused.map(label))}.
      </p>}
    </>}
  </section>;
}
