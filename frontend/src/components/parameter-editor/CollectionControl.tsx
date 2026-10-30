import type { JsonValue } from "@/types/monitoring";
import { AdjacencyField } from "./AdjacencyField";
import { objectValue, type ControlProps } from "./types";

export function CollectionControl(props: ControlProps & {
  features: string[]; featureLabels: Record<string, string>;
}) {
  const { field, value, id, disabled, onChange, features, featureLabels } = props;
  if (field.type === "integer_adjacency")
    return <AdjacencyField label={field.label} value={value} disabled={disabled} onChange={onChange} />;
  if (field.type === "rename") {
    const mapping = objectValue(value);
    return <>{[...new Set([...features, ...Object.keys(mapping)])].map(feature =>
      <label key={feature}>{featureLabels[feature] ?? feature}<input disabled={disabled}
        value={String(mapping[feature] ?? "")} onChange={event => {
          const next = { ...mapping };
          if (event.target.value) next[feature] = event.target.value;
          else delete next[feature];
          onChange(next);
        }} /></label>)}</>;
  }
  const entries: JsonValue[] = Array.isArray(value) ? value : field.type === "number_pair" ? [0, 1] : [];
  if (field.type === "features") return <>
    {!features.length && <p>Connect inputs to select available features.</p>}
    {features.map(feature => <label className="parameter-check" key={feature}>
      <input type="checkbox" disabled={disabled} checked={entries.includes(feature)}
        onChange={event => onChange(event.target.checked ? [...entries, feature]
          : entries.filter(item => item !== feature))} />
      {featureLabels[feature] ?? feature}</label>)}
    <ol>{entries.map((entry, index) => <li key={String(entry)}>
      {featureLabels[String(entry)] ?? String(entry)}
      <button type="button" disabled={disabled || index === 0}
        aria-label={`Move ${entry} earlier`} onClick={() => {
          const next = [...entries];
          [next[index - 1], next[index]] = [next[index]!, next[index - 1]!];
          onChange(next);
        }}>↑</button>
    </li>)}</ol>
  </>;
  return <><div className="parameter-list">{entries.map((entry, index) =>
    <div key={index}><input type="number" step="any" disabled={disabled}
      aria-label={`${field.label} ${index + 1}`} id={`${id}-${index}`}
      value={String(entry ?? "")} onChange={event => onChange(entries.map((item, at) =>
        at === index ? event.target.value === "" ? "" : Number(event.target.value) : item))} />
      {field.type === "number_list" && <button type="button" disabled={disabled}
        aria-label={`Remove ${field.label} ${index + 1}`}
        onClick={() => onChange(entries.filter((_item, at) => at !== index))}>Remove</button>}
    </div>)}</div>
    {field.type === "number_list" && <button type="button" disabled={disabled}
      onClick={() => onChange([...entries, 0])}>Add value</button>}</>;
}
