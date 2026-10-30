import type { JsonValue } from "@/types/monitoring";
import { CollectionControl } from "./CollectionControl";
import { NestedControl } from "./NestedControl";
import { ScalarControl } from "./ScalarControl";
import { hasDefault, initialValue, type FieldDescriptor, type Parameters, type ParameterIssue, type ParameterPath } from "./types";
import "./parameter-editor.css";

export type { FieldDescriptor } from "./types";
type Props = {
  fields: FieldDescriptor[]; values: Parameters; onChange: (values: Parameters) => void;
  features?: string[]; featureLabels?: Record<string, string>; prefix?: string;
  path?: ParameterPath; issues?: ParameterIssue[]; readOnly?: boolean;
};

export function ParameterFields({ fields, values, onChange, features = [], featureLabels = {},
  prefix = "parameter", path = [], issues = [], readOnly }: Props) {
  return <div className="parameter-editor">{fields.map(field => {
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
          render={(nested, next, nextPath, change) => <ParameterFields fields={nested} values={next}
            onChange={change} path={nextPath} issues={issues} features={features}
            featureLabels={featureLabels} readOnly={readOnly || value === null} prefix={id} />} />;
        break;
      case "number_pair": case "number_list": case "features": case "rename": case "integer_adjacency":
        control = <CollectionControl {...props} disabled={field.type === "integer_adjacency" ? readOnly : props.disabled} features={features} featureLabels={featureLabels} />;
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
      {explicit && (hasDefault(field) || !field.required) && <button type="button" disabled={readOnly} onClick={() => {
        const next = { ...values }; delete next[field.name]; onChange(next);
      }}>{hasDefault(field) ? "Use default" : "Leave unset"}</button>}
      <div id={`${id}-errors`}>{messages.map((issue, index) => <p role="alert" key={index} className="parameter-error">{issue.message}</p>)}</div>
    </fieldset>;
  })}</div>;
}
