import { useId, useRef } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { addsByDefault, combinedName, formulaName } from "./scope";

type Issue = { path: (string | number)[]; message: string };
type Change = (params: Record<string, JsonValue>, field: string) => void;

const errorsOf = (issues: Issue[], field: string) => issues.filter((issue) => issue.path[0] === field);

function Errors({ id, issues }: { id: string; issues: Issue[] }) {
  return <div id={id}>
    {issues.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
  </div>;
}

/** Set one setting, or leave it out so the step uses its default. */
function setter(node: PipelineNode, onChange: Change) {
  return (field: string, value: JsonValue | undefined) => {
    const params = { ...node.params };
    if (value === undefined) delete params[field];
    else params[field] = value;
    onChange(params, field);
  };
}

/** The name of the feature an Aggregate or Formula computes. */
export function CombinedName({ node, component, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  issues: Issue[];
  readOnly?: boolean;
  onChange: Change;
}) {
  const id = useId();
  const errors = errorsOf(issues, "name");
  const set = setter(node, onChange);
  const fallback = combinedName({ ...node, params: { ...node.params, name: null } }, component);
  return <div className="pl-field">
    <label htmlFor={`${id}-name`}>Name</label>
    <input id={`${id}-name`} value={typeof node.params.name === "string" ? node.params.name : ""}
      placeholder={fallback} maxLength={120} spellCheck={false} autoComplete="off" disabled={readOnly}
      aria-invalid={errors.length > 0} aria-describedby={`${id}-name-help ${id}-name-errors`}
      onChange={(event) => set("name", event.target.value || undefined)} />
    <small className="pl-help" id={`${id}-name-help`}>
      The computed feature, in letters, digits and underscores. Leave empty for {fallback}.
    </small>
    <Errors id={`${id}-name-errors`} issues={errors} />
  </div>;
}

/** A Formula's expression or a Gate's condition, written over the features that arrive. */
export function PipelineFormula({ node, component, features, featureLabels, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  /** Incoming feature names in their order, once the graph has been checked. */
  features: string[];
  featureLabels: Record<string, string>;
  issues: Issue[];
  readOnly?: boolean;
  onChange: Change;
}) {
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const gate = node.component === "prepare.gate";
  const field = gate ? "condition" : "expression";
  const text = typeof node.params[field] === "string" ? node.params[field] : "";
  const errors = errorsOf(issues, field);
  const set = setter(node, onChange);
  const help = component.fields.find((item) => item.name === field)?.description;
  // A name goes in where the cursor is, replacing any selection, and the cursor follows it.
  const insert = (name: string) => {
    const element = area.current;
    const start = element?.selectionStart ?? text.length;
    const end = element?.selectionEnd ?? text.length;
    const token = formulaName(name);
    set(field, text.slice(0, start) + token + text.slice(end));
    requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(start + token.length, start + token.length);
    });
  };
  const add = (node.params.result ?? (addsByDefault(component) ? "add" : "replace")) === "add";
  const name = combinedName(node, component);
  return <div className="pl-formula">
    <div className="pl-field">
      <label htmlFor={`${id}-text`}>{gate ? "Condition" : "Formula"}</label>
      <textarea ref={area} id={`${id}-text`} className="pl-code" rows={3} maxLength={512} value={text}
        placeholder={gate ? "dc_current > 1" : "dc_voltage * dc_current"} disabled={readOnly}
        spellCheck={false} autoComplete="off" autoCapitalize="off" autoCorrect="off"
        aria-invalid={errors.length > 0} aria-describedby={`${id}-errors ${id}-help`}
        onChange={(event) => set(field, event.target.value)} />
      <Errors id={`${id}-errors`} issues={errors} />
      {!readOnly && features.length > 0 && <div className="pl-formula-names" role="group" aria-label="Insert a feature">
        {features.map((feature) => <button type="button" key={feature} title={featureLabels[feature]}
          aria-label={`Insert ${feature}`} onClick={() => insert(feature)}>{feature}</button>)}
      </div>}
      {help && <small className="pl-help" id={`${id}-help`}>{help}</small>}
    </div>
    {!gate && <>
      <div className="pl-field">
        <span id={`${id}-result`}>Result</span>
        <div className="pl-segmented" role="group" aria-labelledby={`${id}-result`}>
          {(["replace", "add"] as const).map((result) => <button key={result} type="button" disabled={readOnly}
            aria-pressed={add === (result === "add")}
            onClick={() => set("result", result === (addsByDefault(component) ? "add" : "replace") ? undefined : result)}>
            {result === "add" ? "Keep features" : "Replace features"}
          </button>)}
        </div>
        <small className="pl-help">
          {add ? `Keeps the features and adds ${name}.` : `Replaces the features the formula reads with ${name}.`}
        </small>
      </div>
      <CombinedName node={node} component={component} issues={issues} readOnly={readOnly} onChange={onChange} />
    </>}
  </div>;
}
