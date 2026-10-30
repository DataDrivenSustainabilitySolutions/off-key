import type { ReactNode } from "react";
import { fieldDefaults, objectValue, type ControlProps, type FieldDescriptor, type Parameters, type ParameterPath } from "./types";

export function NestedControl({ field, value, disabled, onChange, path, render }: ControlProps & {
  path: ParameterPath;
  render: (fields: FieldDescriptor[], values: Parameters, path: ParameterPath,
    onChange: (values: Parameters) => void) => ReactNode;
}) {
  const entries = field.type === "object_list" ? Array.isArray(value) ? value : [] : [value];
  const changeEntry = (index: number, next: Parameters) => onChange(
    field.type === "object_list" ? entries.map((entry, at) => at === index ? next : entry ?? null) : next);
  return <>{entries.map((entry, index) => {
    const object = objectValue(entry);
    const entryPath = field.type === "object_list" ? [...path, index] : path;
    const selected = String(object[field.discriminator ?? ""] ?? Object.keys(field.variants ?? {})[0] ?? "");
    const fields = field.variants ? field.variants[selected] ?? [] : field.fields ?? [];
    const params = field.type === "component" ? objectValue(object.params) : object;
    return <div key={index} className="parameter-nested">
      {field.type === "component" && <p>{String(object.id ?? "")}</p>}
      {field.variants && field.discriminator && <label>{field.label} kind<select disabled={disabled}
        value={selected} onChange={event => changeEntry(index, {
          ...fieldDefaults(field.variants![event.target.value] ?? []),
          [field.discriminator!]: event.target.value,
        })}>{Object.keys(field.variants).map(kind => <option key={kind}>{kind}</option>)}</select></label>}
      {render(fields.filter(item => item.name !== field.discriminator), params,
        field.type === "component" ? [...entryPath, "params"] : entryPath,
        next => changeEntry(index, field.type === "component" ? { ...object, params: next } : next))}
      {field.type === "object_list" && <button type="button" disabled={disabled}
        onClick={() => onChange(entries.filter((_entry, at) => at !== index).map(entry => entry ?? null))}>Remove item</button>}
    </div>;
  })}
  {field.type === "object_list" && <button type="button" disabled={disabled} onClick={() => {
    const kind = Object.keys(field.variants ?? {})[0];
    const next = fieldDefaults(kind ? field.variants![kind]! : field.fields ?? []);
    if (kind && field.discriminator) next[field.discriminator] = kind;
    onChange([...entries.map(entry => entry ?? null), next]);
  }}>Add item</button>}</>;
}
