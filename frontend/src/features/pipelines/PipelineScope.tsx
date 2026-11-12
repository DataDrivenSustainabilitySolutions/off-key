import { useId, type ReactNode } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { CombinedName } from "./PipelineFormula";
import { addedName, addsByDefault, combinedName, defaultSuffix, isExpectation, listed, setting, stepScope } from "./scope";

type Issue = { path: (string | number)[]; message: string };

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

const APART = {
  against: {
    label: "Against",
    help: "Every feature under Applies to is compared with this one, over the same recent observations.",
  },
  target: {
    label: "Target",
    help: "The feature the step expects from the features below. It gives the target minus the expected value.",
  },
};

/** The one feature a step sets apart from those it uses: what a Rolling relation compares
 * every other feature with, or what an Expected value expects from them. */
export function PipelineApart({ field, node, features, featureLabels, featureHint, issues, readOnly, onChange }: {
  field: keyof typeof APART;
  node: PipelineNode;
  features: string[];
  featureLabels: Record<string, string>;
  featureHint?: ReactNode;
  issues: Issue[];
  readOnly?: boolean;
  onChange: (params: Record<string, JsonValue>, field: string) => void;
}) {
  const id = useId();
  const apart = typeof node.params[field] === "string" ? node.params[field] : "";
  const errors = issues.filter((issue) => issue.path[0] === field);
  const choose = (feature: string) => {
    const params = { ...node.params };
    if (feature) params[field] = feature;
    else delete params[field];
    // The feature set apart is never one the step uses.
    if (Array.isArray(params.apply_to)) {
      const kept = params.apply_to.filter((name) => name !== feature);
      if (kept.length) params.apply_to = kept;
      else delete params.apply_to;
    }
    onChange(params, field);
  };
  return <div className="pl-field">
    <label htmlFor={`${id}-apart`}>{APART[field].label}</label>
    <select id={`${id}-apart`} value={apart} disabled={readOnly} aria-invalid={errors.length > 0}
      aria-describedby={`${id}-apart-help ${id}-apart-errors`} onChange={(event) => choose(event.target.value)}>
      <option value="">Choose a feature</option>
      {features.map((feature) => <option key={feature} value={feature}>{featureLabels[feature] ?? feature}</option>)}
      {apart && !features.includes(apart) && <option value={apart}>{apart} (not available here)</option>}
    </select>
    <small className="pl-help" id={`${id}-apart-help`}>{APART[field].help}</small>
    {!features.length && featureHint}
    <div id={`${id}-apart-errors`}>
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
  // An Expected value expects its target from the features chosen here, one at least.
  const expects = isExpectation(node.component);
  const target = expects && typeof node.params.target === "string" ? node.params.target : "";
  // An Aggregate computes one feature from at least two.
  const computed = combinedName(node, component);
  const fewest = computed === undefined || expects ? 1 : 2;
  const outcome = expects
    ? !target
      ? "Choose a target to see what the step gives."
      : scope.add
        ? `Keeps every feature and adds ${computed}.`
        : `Replaces ${chosen ? listed([target, ...used]) : "every feature"} with ${computed}.`
    : computed !== undefined
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
      <legend>{expects ? "Expected from" : "Applies to"}</legend>
      <small className="pl-help" id={`${id}-applies`}>
        {chosen ? `${plural(chosen.length, "feature")} of ${features.length}`
          : expects ? "Every other feature that arrives" : "Every feature that arrives"}
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
