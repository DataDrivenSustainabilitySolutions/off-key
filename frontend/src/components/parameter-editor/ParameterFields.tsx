import { useState, type ReactNode } from "react";
import type { JsonValue } from "@/types/monitoring";
import { CollectionControl } from "./CollectionControl";
import { NestedControl } from "./NestedControl";
import { ScalarControl } from "./ScalarControl";
import { fieldApplies, hasDefault, initialValue, type FieldDescriptor, type Parameters, type ParameterIssue, type ParameterPath } from "./types";
import "./parameter-editor.css";

export type { FieldDescriptor } from "./types";
type Props = {
  fields: FieldDescriptor[]; values: Parameters; onChange: (values: Parameters) => void;
  features?: string[]; featureLabels?: Record<string, string>; prefix?: string;
  /** Shown in place of a feature list while the features are unknown. */
  featureHint?: ReactNode;
  path?: ParameterPath; issues?: ParameterIssue[]; readOnly?: boolean;
};

/** Fewer advanced settings than this are listed with the others. */
const FOLD_FROM = 3;

/** The value a setting among these has, set or by default. */
const current = (fields: FieldDescriptor[], values: Parameters, name: string): JsonValue | undefined => {
  if (Object.prototype.hasOwnProperty.call(values, name)) return values[name];
  const field = fields.find(item => item.name === name);
  return field && hasDefault(field) ? field.default ?? null : undefined;
};

export function ParameterFields({ fields, values, onChange, features = [], featureLabels = {}, featureHint,
  prefix = "parameter", path = [], issues = [], readOnly }: Props) {
  const shown = fields.filter(field => fieldApplies(field, current(fields, values, field.shown_when?.field ?? "")));
  const advanced = shown.filter(field => field.advanced);
  // A step's key settings come first; the others wait under More settings.
  const folded = advanced.length >= FOLD_FROM && advanced.length < shown.length ? advanced : [];
  const main = shown.filter(field => !folded.includes(field));
  // Open from the start where a folded setting was changed, and as soon as one is at fault, so neither
  // hides. A new step writes every default out, so being written is not being changed.
  const [more, setMore] = useState(() => folded.some(field => Object.prototype.hasOwnProperty.call(values, field.name)
    && !(hasDefault(field) && JSON.stringify(values[field.name]) === JSON.stringify(field.default ?? null))));
  const atFault = folded.some(field => issues.some(issue => String(issue.path[path.length]) === field.name
    && JSON.stringify(issue.path.slice(0, path.length).map(String)) === JSON.stringify(path.map(String))));
  const render = (field: FieldDescriptor) => {
    const fieldPath = [...path, field.name];
    const id = `${prefix}-${field.name}`;
    const explicit = Object.prototype.hasOwnProperty.call(values, field.name);
    const value = explicit ? values[field.name] : hasDefault(field) ? field.default : undefined;
    const nested = field.type === "object" || field.type === "object_list" || field.type === "component";
    const messages = issues.filter(issue =>
      JSON.stringify((nested ? issue.path : issue.path.slice(0, fieldPath.length)).map(String)) === JSON.stringify(fieldPath.map(String)));
    const update = (next: JsonValue) => onChange({ ...values, [field.name]: next });
    const props = { field, value, id, disabled: readOnly || value === null, invalid: messages.length > 0, onChange: update };
    let control;
    switch (field.type) {
      case "object": case "object_list": case "component":
        control = <NestedControl {...props} path={fieldPath}
          render={(nested, next, nextPath, change, index) => <ParameterFields fields={nested} values={next}
            onChange={change} path={nextPath} issues={issues} features={features}
            featureLabels={featureLabels} featureHint={featureHint} readOnly={readOnly || value === null} prefix={`${id}-${index}`} />} />;
        break;
      case "number_pair": case "number_list": case "features": case "rename": case "integer_adjacency":
        control = <CollectionControl {...props} disabled={field.type === "integer_adjacency" ? readOnly : props.disabled} features={features} featureLabels={featureLabels} featureHint={featureHint} />;
        break;
      case "number": case "integer": case "string": case "boolean": case "enum":
        control = <ScalarControl {...props} />;
        break;
    }
    return <fieldset key={field.name} className="parameter-field" aria-invalid={messages.length > 0}
      aria-describedby={`${id}-description ${id}-errors`}>
      <legend><label htmlFor={id}>{field.label}{field.required && !hasDefault(field) ? " *" : ""}</label></legend>
      {control}
      <div id={`${id}-description`} className="parameter-help">
        {field.description && <p>{field.description}</p>}
        {(field.exclusive_minimum != null || field.exclusive_maximum != null) && <p>
          {field.exclusive_minimum != null ? `Greater than ${field.exclusive_minimum}. ` : ""}
          {field.exclusive_maximum != null ? `Less than ${field.exclusive_maximum}.` : ""}
        </p>}
      </div>
      {field.nullable && field.type !== "integer_adjacency" && <label className="parameter-check">
        <input type="checkbox" aria-label={`${field.label} automatic`} disabled={readOnly}
          checked={value === null} onChange={event => update(event.target.checked ? null : initialValue(field))} />
        Automatic / none
      </label>}
      {explicit && (hasDefault(field) || !field.required) && <button type="button" className="parameter-reset" disabled={readOnly} onClick={() => {
        const next = { ...values }; delete next[field.name]; onChange(next);
      }}>{hasDefault(field) ? "Use default" : "Leave unset"}</button>}
      <div id={`${id}-errors`}>{messages.map((issue, index) => <p role="alert" key={index} className="parameter-error">{issue.message}</p>)}</div>
    </fieldset>;
  };
  return <div className="parameter-editor">
    {main.map(render)}
    {folded.length > 0 && <details className="parameter-more" open={more || atFault}
      onToggle={event => setMore(event.currentTarget.open)}>
      <summary>More settings</summary>
      <div className="parameter-editor">{folded.map(render)}</div>
    </details>}
  </div>;
}
