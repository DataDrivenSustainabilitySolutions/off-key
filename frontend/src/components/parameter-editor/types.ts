import type { JsonValue } from "../../types/monitoring";
import type { ComponentField } from "../../types/pipelines.generated";

export type FieldDescriptor = Omit<ComponentField, "default" | "options" | "fields" | "variants"> & {
  default?: JsonValue;
  options?: JsonValue[] | null;
  fields?: FieldDescriptor[];
  variants?: Record<string, FieldDescriptor[]> | null;
};
export type ParameterPath = (string | number)[];
export type ParameterIssue = { path: ParameterPath; message: string };
export type Parameters = Record<string, JsonValue>;
export type ControlProps = {
  field: FieldDescriptor;
  value: JsonValue | undefined;
  id: string;
  disabled?: boolean;
  invalid?: boolean;
  onChange: (value: JsonValue) => void;
};

export const hasDefault = (field: FieldDescriptor) => field.has_default ?? field.default !== undefined;

export const fieldDefaults = (fields: readonly FieldDescriptor[]): Parameters =>
  Object.fromEntries(fields.filter(hasDefault)
    .map(field => [field.name, structuredClone(field.default ?? null)]));

export const objectValue = (value: JsonValue | undefined): Parameters =>
  value && typeof value === "object" && !Array.isArray(value) ? value : {};

export function hasParameterControl(fields: FieldDescriptor[], path: ParameterPath | null | undefined): boolean {
  if (!path?.length) return false;
  const field = fields.find(item => item.name === path[0]);
  if (!field) return false;
  if (path.length === 1) return true;
  if (field.type === "component") return path[1] === "params" &&
    hasParameterControl(field.fields ?? [], path.slice(2));
  if (field.type === "object" || field.type === "object_list") {
    const nested = field.variants ? Object.values(field.variants).flat() : field.fields ?? [];
    return hasParameterControl(nested, path.slice(field.type === "object_list" ? 2 : 1));
  }
  return ["number_pair", "number_list", "features", "rename", "integer_adjacency"].includes(field.type);
}

export function initialValue(field: FieldDescriptor): JsonValue {
  if (hasDefault(field) && field.default != null) return structuredClone(field.default);
  switch (field.type) {
    case "boolean": return false;
    case "enum": return field.options?.[0] ?? "";
    case "integer": case "number": return 0;
    case "number_pair": return [0, 1];
    case "number_list": case "object_list": case "features": return [];
    case "object": case "rename": case "integer_adjacency": return fieldDefaults(field.fields ?? []);
    case "component": return { id: "", params: fieldDefaults(field.fields ?? []) };
    case "string": return "";
  }
}
