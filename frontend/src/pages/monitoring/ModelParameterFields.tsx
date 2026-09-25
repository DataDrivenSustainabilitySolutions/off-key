import { cn } from "@/lib/utils";
import type { JsonValue, ParameterSchema } from "@/types/monitoring";
import { humanize } from "./config";
import type { FieldErrors } from "./config";
import { CONTROL_CLASS, HELP_CLASS, LABEL_CLASS } from "./formStyles";
import { FieldError } from "./MonitoringUi";

interface Props {
  properties: Record<string, ParameterSchema>;
  values: Record<string, JsonValue>;
  onChange: (values: Record<string, JsonValue>, field: string) => void;
  errors: FieldErrors;
  prefix?: string;
}

export function ModelParameterFields({ properties, values, onChange, errors, prefix = "model" }: Props) {
  return Object.entries(properties).map(([key, schema]) => {
    const type = schema.type ?? schema.anyOf?.find((item) => item.type !== "null")?.type;
    const value = Object.prototype.hasOwnProperty.call(values, key) ? values[key] : schema.default;
    const field = `${prefix}.${key}`;
    const id = `adaptive-param-${field}`;
    const update = (next: JsonValue) => onChange({ ...values, [key]: next }, field);
    const nullable = schema.type === "null" || schema.anyOf?.some((item) => item.type === "null");
    const isNone = value === null;
    const nonNullValue = schema.default ?? (type === "boolean" ? false : type === "array" ? [] : type === "object" ? {} : "");

    if (schema["x-aberrant-component-kind"] && schema.properties?.params?.properties) {
      const component = typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
      const params = component.params;
      return <fieldset key={key} className="sm:col-span-2">
        <legend className={LABEL_CLASS}>{humanize(key)} · {String(component.id ?? "")}</legend>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <ModelParameterFields
            properties={schema.properties.params.properties}
            values={typeof params === "object" && params !== null && !Array.isArray(params) ? params : {}}
            prefix={`${field}.params`}
            errors={errors}
            onChange={(next, changedField) => onChange({ ...values, [key]: { ...component, params: next } }, changedField)}
          />
        </div>
        <FieldError field={field} errors={errors} />
      </fieldset>;
    }

    return <div key={key}>
      <div className="flex items-center justify-between gap-2">
        <label className={LABEL_CLASS} htmlFor={id}>{humanize(key)}</label>
        {nullable && <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" aria-label={`${humanize(key)} is None`} checked={isNone} onChange={(event) => update(event.target.checked ? null : nonNullValue)} />None
        </label>}
      </div>
      {schema.enum ? (
        <select id={id} disabled={isNone} className={cn(CONTROL_CLASS, "mt-2")} value={JSON.stringify(value)} onChange={(event) => update(JSON.parse(event.target.value) as JsonValue)}>
          {schema.enum.map((option) => <option key={JSON.stringify(option)} value={JSON.stringify(option)}>{option === null ? "None" : String(option)}</option>)}
        </select>
      ) : type === "boolean" ? (
        <label className="mt-3 flex items-center gap-2 text-sm"><input id={id} type="checkbox" disabled={isNone} checked={Boolean(value)} onChange={(event) => update(event.target.checked)} />Enabled</label>
      ) : type === "array" || type === "object" ? (
        <textarea id={id} disabled={isNone} className={cn(CONTROL_CLASS, "mt-2 min-h-20 font-mono text-xs")} value={isNone ? "" : typeof value === "string" ? value : JSON.stringify(value ?? (type === "array" ? [] : {}))} onChange={(event) => update(event.target.value)} />
      ) : (
        <input id={id} disabled={isNone} type={type === "number" || type === "integer" ? "number" : "text"} step={type === "integer" ? 1 : "any"} min={schema.minimum} max={schema.maximum} className={cn(CONTROL_CLASS, "mt-2")} value={isNone ? "" : String(value ?? "")} onChange={(event) => update(event.target.value)} />
      )}
      <p className={HELP_CLASS}>{schema.description}</p>
      <FieldError field={field} errors={errors} />
    </div>;
  });
}
