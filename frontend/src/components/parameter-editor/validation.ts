import { ApiRequestError } from "@/lib/api-client";
import { objectValue, type FieldDescriptor, type Parameters, type ParameterIssue, type ParameterPath } from "./types";
import type { JsonValue } from "@/types/monitoring";

function validateParameters(fields: FieldDescriptor[], values: Parameters,
  path: ParameterPath = []): ParameterIssue[] {
  const issues: ParameterIssue[] = [];
  const error = (at: ParameterPath, message: string) => issues.push({ path: at, message });
  for (const field of fields) {
    const at = [...path, field.name];
    const explicit = Object.prototype.hasOwnProperty.call(values, field.name);
    const value = explicit ? values[field.name] : field.has_default ? field.default : undefined;
    if (value === undefined) {
      if (field.required) error(at, `${field.label} is required.`);
      continue;
    }
    if (value === null) {
      if (!field.nullable) error(at, `${field.label} cannot be null.`);
      continue;
    }
    if (field.type === "number" || field.type === "integer") {
      if (typeof value !== "number" || !Number.isFinite(value))
        error(at, `${field.label} must be a number.`);
      else if (field.type === "integer" && !Number.isInteger(value))
        error(at, `${field.label} must be an integer.`);
      else if (field.minimum != null && value < field.minimum)
        error(at, `${field.label} must be at least ${field.minimum}.`);
      else if (field.maximum != null && value > field.maximum)
        error(at, `${field.label} must be at most ${field.maximum}.`);
      else if (field.exclusive_minimum != null && value <= field.exclusive_minimum)
        error(at, `${field.label} must be greater than ${field.exclusive_minimum}.`);
      else if (field.exclusive_maximum != null && value >= field.exclusive_maximum)
        error(at, `${field.label} must be less than ${field.exclusive_maximum}.`);
    } else if (field.type === "boolean" && typeof value !== "boolean")
      error(at, `${field.label} must be a boolean.`);
    else if (field.type === "string" && typeof value !== "string")
      error(at, `${field.label} must be text.`);
    else if (field.type === "enum" && !field.options?.some(option => JSON.stringify(option) === JSON.stringify(value)))
      error(at, `Choose a value for ${field.label}.`);
    else if (field.type === "number_pair" || field.type === "number_list") {
      if (!Array.isArray(value)) error(at, `${field.label} must be a list.`);
      else {
        if (field.type === "number_pair" && value.length !== 2) error(at, "Enter two numbers.");
        value.forEach((item, index) => {
          if (typeof item !== "number" || !Number.isFinite(item)) error([...at, index], "Enter a number.");
        });
      }
    } else if (["object", "object_list", "component"].includes(field.type)) {
      const entries = field.type === "object_list" ? Array.isArray(value) ? value : [] : [value];
      entries.forEach((entry, index) => {
        const object = objectValue(entry);
        const entryPath = field.type === "object_list" ? [...at, index] : at;
        const selected = String(object[field.discriminator ?? ""] ?? "");
        const nested = field.variants ? field.variants[selected] ?? [] : field.fields ?? [];
        issues.push(...validateParameters(nested, field.type === "component" ? objectValue(object.params) : object,
          field.type === "component" ? [...entryPath, "params"] : entryPath));
      });
    }
  }
  return issues;
}

/** Translate machine locations from the existing API contract into form keys. */
export function modelErrorFields(error: unknown): Record<string, string> {
  if (!(error instanceof ApiRequestError)) return {};
  return Object.fromEntries(error.issues.flatMap(issue => {
    const index = issue.loc.indexOf("model_params");
    return index < 0 ? [] : [[["model", ...issue.loc.slice(index + 1)].join("."), issue.msg]];
  }));
}

export function formParameterIssues(errors: Record<string, string>): ParameterIssue[] {
  return Object.entries(errors).filter(([field]) => field.startsWith("model."))
    .map(([field, message]) => ({ path: field.slice("model.".length).split("."), message }));
}

/** Preserve omission and explicit null; controls already produce typed JSON. */
export function validateModelParameters(values: Record<string, JsonValue>, fields: FieldDescriptor[],
  errors: Record<string, string>): Parameters {
  for (const issue of validateParameters(fields, values))
    errors[["model", ...issue.path].join(".")] = issue.message;
  return structuredClone(values);
}
