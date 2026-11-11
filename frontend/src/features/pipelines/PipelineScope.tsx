import { useId, type ReactNode } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { CombinedName } from "./PipelineFormula";
import { addedName, addsByDefault, combinedName, defaultSuffix, listed, setting, stepScope } from "./scope";

type Issue = { path: (string | number)[]; message: string };

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

/** The one feature a Rolling relation compares every other feature with. */
export function PipelineAgainst({ node, features, featureLabels, featureHint, issues, readOnly, onChange }: {
  node: PipelineNode;
  features: string[];
  featureLabels: Record<string, string>;
  featureHint?: ReactNode;
  issues: Issue[];
  readOnly?: boolean;
  onChange: (params: Record<string, JsonValue>, field: string) => void;
}) {
  const id = useId();
  const against = typeof node.params.against === "string" ? node.params.against : "";
  const errors = issues.filter((issue) => issue.path[0] === "against");
  const choose = (feature: string) => {
    const params = { ...node.params };
    if (feature) params.against = feature;
    else delete params.against;
    // The compared feature is never one the step uses.
    if (Array.isArray(params.apply_to)) {
      const kept = params.apply_to.filter((name) => name !== feature);
      if (kept.length) params.apply_to = kept;
      else delete params.apply_to;
    }
    onChange(params, "against");
  };
  return <div className="pl-field">
    <label htmlFor={`${id}-against`}>Against</label>
    <select id={`${id}-against`} value={against} disabled={readOnly} aria-invalid={errors.length > 0}
      aria-describedby={`${id}-against-help ${id}-against-errors`} onChange={(event) => choose(event.target.value)}>
      <option value="">Choose a feature</option>
      {features.map((feature) => <option key={feature} value={feature}>{featureLabels[feature] ?? feature}</option>)}
      {against && !features.includes(against) && <option value={against}>{against} (not available here)</option>}
    </select>
    <small className="pl-help" id={`${id}-against-help`}>
      Every feature under Applies to is compared with this one, over the same recent observations.
    </small>
    {!features.length && featureHint}
    <div id={`${id}-against-errors`}>
      {errors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
    </div>
  </div>;
}

/** Applies to and Result: which incoming features a step uses and where its output goes. */
export function PipelineScope({ node, component, features, featureLabels, featureHint, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  /** Incoming feature names in their order, once the graph has been checked. */
  features: string[];
  featureLabels: Record<string, string>;
  /** Shown in place of the features while they are unknown: why, and where to fix it. */
  featureHint?: ReactNode;
  issues: Issue[];
  readOnly?: boolean;
  onChange: (params: Record<string, JsonValue>, field: string) => void;
}) {
  const id = useId();
  const scope = stepScope(node, component)!;
  const chosen = scope.applyTo;
  // Names that no longer arrive stay listed until they are unchecked.
  const missing = chosen?.filter((name) => !features.includes(name)) ?? [];
  const used = chosen ?? features;
  const messages = (field: string) => issues.filter((issue) => issue.path[0] === field);
  const set = (field: string, value: JsonValue | undefined) => {
    const params = { ...node.params };
    if (value === undefined) delete params[field];
    else params[field] = value;
    onChange(params, field);
  };
  const toggle = (name: string, checked: boolean) => {
    const next = features.filter((feature) =>
      feature === name ? checked : chosen ? chosen.includes(feature) : true);
    const kept = missing.filter((feature) => feature !== name);
    // Every feature checked is the default: the step follows what arrives.
    set("apply_to", next.length === features.length && !kept.length ? undefined : [...next, ...kept]);
  };
  const components = typeof node.params.n_components === "number" ? node.params.n_components : 1;
  // A Range check that skips leaves values unchanged, so there is nothing to add.
  const keepsValues = node.component === "prepare.range" && setting(node, component, "action") === "skip";
  // An Aggregate computes one feature from at least two.
  const computed = combinedName(node, component);
  const fewest = computed === undefined ? 1 : 2;
  const outcome = computed !== undefined
    ? scope.add
      ? `Keeps the features and adds ${computed}.`
      : `Replaces ${chosen ? listed(used) : "the features"} with ${computed}.`
    : scope.elementwise
    ? scope.add
      ? used.length ? `Keeps the values and adds ${listed(used.map((name) => addedName(name, scope.suffix ?? "new")))}.` : "Keeps the values and adds a copy of each."
      : keepsValues
        ? "Skips observations outside the range; the values that pass stay the same."
        : "Changes the values in place; the names stay the same."
    : scope.add
      ? `Keeps every feature and adds ${plural(components, "component")}.`
      : chosen
        ? `Replaces ${listed(used.map((name) => featureLabels[name] ?? name))} with ${plural(components, "component")}.`
        : `Replaces every feature with ${plural(components, "component")}.`;
  const applyErrors = messages("apply_to");
  const suffixErrors = messages("suffix");
  const defaultResult = addsByDefault(component) ? "add" : "replace";
  return <div className="pl-scope">
    <fieldset className="pl-field" aria-describedby={`${id}-applies ${id}-applies-errors`}>
      <legend>Applies to</legend>
      <small className="pl-help" id={`${id}-applies`}>
        {chosen ? `${plural(chosen.length, "feature")} of ${features.length}` : "Every feature that arrives"}
      </small>
      {!features.length && !missing.length
        ? featureHint ?? <p className="pl-help">Connect an input to choose features.</p>
        : <div className="pl-scope-features">
          {features.map((name) => {
            const checked = !chosen || chosen.includes(name);
            return <label className="parameter-check" key={name}>
              <input type="checkbox" checked={checked} disabled={readOnly || (checked && used.length <= fewest)}
                onChange={(event) => toggle(name, event.target.checked)} />
              {featureLabels[name] ?? name}
            </label>;
          })}
          {missing.map((name) => <label className="parameter-check is-missing" key={name}>
            <input type="checkbox" checked disabled={readOnly} onChange={() => toggle(name, false)} />
            {name} <small>not available here</small>
          </label>)}
        </div>}
      <div id={`${id}-applies-errors`}>
        {applyErrors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
      </div>
    </fieldset>
    <div className="pl-field">
      <span id={`${id}-result`}>Result</span>
      <div className="pl-segmented" role="group" aria-labelledby={`${id}-result`}>
        {(["replace", "add"] as const).map((result) => <button key={result} type="button"
          disabled={readOnly || (result === "add" && keepsValues && !scope.add)}
          aria-pressed={scope.add === (result === "add")}
          onClick={() => set("result", result === defaultResult ? undefined : result)}>
          {result === "add" ? scope.elementwise ? "Add new features" : "Keep features" : scope.elementwise ? "Replace values" : "Replace features"}
        </button>)}
      </div>
      <small className="pl-help">{outcome}</small>
      {node.component === "prepare.despike" && !scope.add && <small className="pl-help">
        The detector sees the median in place of a spike. The raw value stays in the evidence.
      </small>}
    </div>
    {computed !== undefined
      && <CombinedName node={node} component={component} issues={issues} readOnly={readOnly} onChange={onChange} />}
    {scope.elementwise && scope.add && <div className="pl-field">
      <label htmlFor={`${id}-suffix`}>Suffix</label>
      <input id={`${id}-suffix`} value={typeof node.params.suffix === "string" ? node.params.suffix : ""} disabled={readOnly}
        placeholder={defaultSuffix(node, component)}
        maxLength={24} aria-invalid={suffixErrors.length > 0} aria-describedby={`${id}-suffix-help ${id}-suffix-errors`}
        onChange={(event) => set("suffix", event.target.value || undefined)} />
      <small className="pl-help" id={`${id}-suffix-help`}>Added features are named feature_{scope.suffix ?? "suffix"}.</small>
      <div id={`${id}-suffix-errors`}>
        {suffixErrors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
      </div>
    </div>}
  </div>;
}
