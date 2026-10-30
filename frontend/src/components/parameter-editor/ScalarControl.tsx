import { hasDefault, type ControlProps } from "./types";

export function ScalarControl({ field, value, id, disabled, invalid, onChange }: ControlProps) {
  const common = { id, disabled, "aria-label": field.label, "aria-invalid": invalid,
    "aria-describedby": `${id}-description` };
  if (field.type === "boolean") return <input {...common} type="checkbox"
    checked={value === true} onChange={event => onChange(event.target.checked)} />;
  if (field.type === "enum") return <select {...common} value={JSON.stringify(value) ?? ""}
    onChange={event => onChange(JSON.parse(event.target.value))}>
    {value === undefined && <option value="">Choose a value</option>}
    {(field.options ?? []).map(option => <option key={JSON.stringify(option)}
      value={JSON.stringify(option)}>{String(option)}</option>)}
  </select>;
  const numeric = field.type === "number" || field.type === "integer";
  return <input {...common} type={numeric ? "number" : "text"}
    step={field.type === "integer" ? 1 : "any"}
    min={field.minimum ?? undefined} max={field.maximum ?? undefined}
    required={field.required && !hasDefault(field)}
    value={String(value ?? "")}
    onChange={event => onChange(numeric && event.target.value !== ""
      ? Number(event.target.value) : event.target.value)} />;
}
