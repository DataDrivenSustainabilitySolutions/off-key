import type { JsonValue } from "@/types/monitoring";
import { AdjacencyField } from "./AdjacencyField";

/** Deliberately bounded controls; the server owns schema validation. */
export type FieldDescriptor = {
  name: string;
  label: string;
  type:
    | "number"
    | "integer"
    | "boolean"
    | "string"
    | "enum"
    | "features"
    | "rename"
    | "number_pair"
    | "number_list"
    | "object"
    | "object_list"
    | "component"
    | "integer_adjacency";
  description?: string;
  default?: JsonValue;
  minimum?: number;
  maximum?: number;
  nullable?: boolean;
  options?: JsonValue[];
  fields?: FieldDescriptor[];
  discriminator?: string;
  variants?: Record<string, FieldDescriptor[]>;
};

type Props = {
  fields: FieldDescriptor[];
  values: Record<string, JsonValue>;
  features: string[];
  featureLabels?: Record<string, string>;
  onChange: (values: Record<string, JsonValue>) => void;
  prefix?: string;
  readOnly?: boolean;
};
export function ParameterFields({
  fields,
  values,
  features,
  featureLabels = {},
  onChange,
  prefix = "parameter",
  readOnly,
}: Props) {
  return (
    <>
      {fields.map((field) => {
        const id = `${prefix}-${field.name}`;
        const value = Object.prototype.hasOwnProperty.call(values, field.name)
          ? values[field.name]
          : field.default;
        const update = (next: JsonValue) =>
          onChange({ ...values, [field.name]: next });
        const label = <span>{field.label}</span>;
        if (field.type === "integer_adjacency")
          return (
            <AdjacencyField
              key={field.name}
              label={field.label}
              value={value}
              disabled={readOnly}
              onChange={update}
            />
          );
        if (field.variants && field.discriminator) {
          const entries =
            field.type === "object_list"
              ? Array.isArray(value)
                ? value
                : []
              : [value];
          const renderEntry = (entry: JsonValue | undefined, index: number) => {
            const object =
              entry && typeof entry === "object" && !Array.isArray(entry)
                ? entry
                : {};
            const selected = String(
              object[field.discriminator!] ??
                Object.keys(field.variants!)[0] ??
                "",
            );
            const updateEntry = (next: Record<string, JsonValue>) =>
              update(
                field.type === "object_list"
                  ? entries.map((item, at) =>
                      at === index ? next : (item ?? null),
                    )
                  : next,
              );
            return (
              <div className="pl-repeat-item" key={index}>
                <label className="pl-field">
                  <span>{field.label} kind</span>
                  <select
                    disabled={readOnly}
                    value={selected}
                    onChange={(event) => {
                      const defaults = Object.fromEntries(
                        (field.variants![event.target.value] ?? [])
                          .filter((item) => item.default !== undefined)
                          .map((item) => [item.name, item.default!]),
                      );
                      updateEntry({
                        ...defaults,
                        [field.discriminator!]: event.target.value,
                      });
                    }}
                  >
                    {Object.keys(field.variants!).map((key) => (
                      <option key={key} value={key}>
                        {key.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <ParameterFields
                  fields={(field.variants![selected] ?? []).filter(
                    (item) => item.name !== field.discriminator,
                  )}
                  values={object}
                  features={features}
                  featureLabels={featureLabels}
                  prefix={`${id}-${index}`}
                  readOnly={readOnly}
                  onChange={updateEntry}
                />
                {field.type === "object_list" && !readOnly && (
                  <button
                    type="button"
                    onClick={() =>
                      update(
                        entries
                          .filter((_item, at) => at !== index)
                          .map((item) => item ?? null),
                      )
                    }
                  >
                    Remove item
                  </button>
                )}
              </div>
            );
          };
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              {entries.map(renderEntry)}
              {field.type === "object_list" && !readOnly && (
                <button
                  type="button"
                  onClick={() => {
                    const kind = Object.keys(field.variants!)[0]!;
                    update([
                      ...entries.map((item) => item ?? null),
                      {
                        ...Object.fromEntries(
                          (field.variants![kind] ?? [])
                            .filter((item) => item.default !== undefined)
                            .map((item) => [item.name, item.default!]),
                        ),
                        [field.discriminator!]: kind,
                      },
                    ]);
                  }}
                >
                  Add item
                </button>
              )}
            </fieldset>
          );
        }
        if (field.type === "component") {
          const component =
            value && typeof value === "object" && !Array.isArray(value)
              ? value
              : {};
          const params = component.params;
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>
                {field.label} · {String(component.id ?? "")}
              </legend>
              <ParameterFields
                fields={field.fields ?? []}
                values={
                  params && typeof params === "object" && !Array.isArray(params)
                    ? params
                    : {}
                }
                features={features}
                featureLabels={featureLabels}
                readOnly={readOnly}
                prefix={id}
                onChange={(next) => update({ ...component, params: next })}
              />
            </fieldset>
          );
        }
        if (field.type === "features")
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              <p className="pl-help">
                Features are emitted in the order selected below.
              </p>
              {features.map((feature) => (
                <label key={feature} className="pl-check">
                  <input
                    type="checkbox"
                    disabled={readOnly}
                    checked={Array.isArray(value) && value.includes(feature)}
                    onChange={(event) =>
                      update(
                        event.target.checked
                          ? [...(Array.isArray(value) ? value : []), feature]
                          : (Array.isArray(value) ? value : []).filter(
                              (item) => item !== feature,
                            ),
                      )
                    }
                  />
                  {featureLabels[feature] ?? feature}
                </label>
              ))}
              {!features.length && (
                <p className="pl-help">
                  {readOnly
                    ? "Input lineage is unavailable in this snapshot. Saved selections are listed below."
                    : "Available input features are not inferred yet. Connect this component, then validate the graph if they do not appear."}
                </p>
              )}
              {Array.isArray(value) && value.length > 0 && (
                <ol className="pl-feature-order">
                  {value.map((feature, index) => (
                    <li key={String(feature)}>
                      {featureLabels[String(feature)] ?? String(feature)}
                      <button
                        type="button"
                        disabled={readOnly || index === 0}
                        aria-label={`Move ${String(feature)} earlier`}
                        onClick={() => {
                          const next = [...value];
                          [next[index - 1], next[index]] = [
                            next[index]!,
                            next[index - 1]!,
                          ];
                          update(next);
                        }}
                      >
                        ↑
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </fieldset>
          );
        if (field.type === "rename") {
          const mapping =
            value && typeof value === "object" && !Array.isArray(value)
              ? value
              : {};
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              {[...new Set([...features, ...Object.keys(mapping)])].map(
                (feature) => (
                  <label key={feature} className="pl-field">
                    <span>{featureLabels[feature] ?? feature}</span>
                    <input
                      value={String(mapping[feature] ?? "")}
                      placeholder={feature}
                      disabled={readOnly}
                      onChange={(event) => {
                        const next = { ...mapping };
                        if (event.target.value)
                          next[feature] = event.target.value;
                        else delete next[feature];
                        update(next);
                      }}
                    />
                  </label>
                ),
              )}
            </fieldset>
          );
        }
        if (field.type === "object")
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              <ParameterFields
                fields={field.fields ?? []}
                values={
                  value && typeof value === "object" && !Array.isArray(value)
                    ? value
                    : {}
                }
                features={features}
                featureLabels={featureLabels}
                onChange={update}
                prefix={id}
                readOnly={readOnly}
              />
            </fieldset>
          );
        if (field.type === "object_list") {
          const entries = Array.isArray(value) ? value : [];
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              {entries.map((entry, index) => (
                <div key={index} className="pl-repeat-item">
                  <ParameterFields
                    fields={field.fields ?? []}
                    values={
                      entry &&
                      typeof entry === "object" &&
                      !Array.isArray(entry)
                        ? entry
                        : {}
                    }
                    features={features}
                    featureLabels={featureLabels}
                    readOnly={readOnly}
                    prefix={`${id}-${index}`}
                    onChange={(next) =>
                      update(
                        entries.map((item, at) => (at === index ? next : item)),
                      )
                    }
                  />
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() =>
                        update(entries.filter((_item, at) => at !== index))
                      }
                    >
                      Remove {field.label.toLowerCase().replace(/s$/, "")}
                    </button>
                  )}
                </div>
              ))}
              {!readOnly && (
                <button
                  type="button"
                  onClick={() =>
                    update([
                      ...entries,
                      Object.fromEntries(
                        (field.fields ?? [])
                          .filter((item) => item.default !== undefined)
                          .map((item) => [item.name, item.default!]),
                      ),
                    ])
                  }
                >
                  Add {field.label.toLowerCase().replace(/s$/, "")}
                </button>
              )}
            </fieldset>
          );
        }
        if (field.type === "number_pair" || field.type === "number_list") {
          const entries = Array.isArray(value)
            ? value
            : field.type === "number_pair"
              ? [0, 1]
              : [];
          return (
            <fieldset key={field.name} className="pl-field">
              <legend>{field.label}</legend>
              <div className="pl-number-list">
                {entries.map((entry, index) => (
                  <div key={index}>
                    <input
                      type="number"
                      step="any"
                      aria-label={`${field.label} ${index + 1}`}
                      value={String(entry ?? "")}
                      disabled={readOnly}
                      onChange={(event) =>
                        update(
                          entries.map((item, at) =>
                            at === index
                              ? event.target.value === ""
                                ? ""
                                : Number(event.target.value)
                              : item,
                          ),
                        )
                      }
                    />
                    {field.type === "number_list" && !readOnly && (
                      <button
                        type="button"
                        aria-label={`Remove ${field.label} ${index + 1}`}
                        onClick={() =>
                          update(entries.filter((_item, at) => at !== index))
                        }
                      >
                        ×
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {field.type === "number_list" && !readOnly && (
                <button type="button" onClick={() => update([...entries, 0])}>
                  Add value
                </button>
              )}
            </fieldset>
          );
        }
        return (
          <label
            key={field.name}
            className={`pl-field${field.type === "boolean" ? " pl-field--check" : ""}`}
            htmlFor={id}
          >
            {label}
            {field.type === "boolean" ? (
              <input
                id={id}
                aria-label={field.label}
                aria-describedby={field.description ? `${id}-help` : undefined}
                type="checkbox"
                checked={Boolean(value)}
                disabled={readOnly}
                onChange={(event) => update(event.target.checked)}
              />
            ) : field.type === "enum" ? (
              <select
                id={id}
                aria-label={field.label}
                aria-describedby={field.description ? `${id}-help` : undefined}
                disabled={readOnly}
                value={JSON.stringify(value)}
                onChange={(event) =>
                  update(JSON.parse(event.target.value) as JsonValue)
                }
              >
                {(field.options ?? []).map((option) => (
                  <option
                    key={JSON.stringify(option)}
                    value={JSON.stringify(option)}
                  >
                    {String(option ?? "None")}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                aria-label={field.label}
                aria-describedby={field.description ? `${id}-help` : undefined}
                type={
                  field.type === "number" || field.type === "integer"
                    ? "number"
                    : "text"
                }
                disabled={readOnly || (field.nullable && value === null)}
                step={field.type === "integer" ? 1 : "any"}
                min={field.minimum}
                max={field.maximum}
                value={String(value ?? "")}
                onChange={(event) =>
                  update(
                    field.type === "number" || field.type === "integer"
                      ? event.target.value === ""
                        ? ""
                        : Number(event.target.value)
                      : event.target.value,
                  )
                }
              />
            )}
            {field.nullable && (
              <span className="pl-check">
                <input
                  aria-label={`${field.label} automatic`}
                  type="checkbox"
                  checked={value === null}
                  disabled={readOnly}
                  onChange={(event) =>
                    update(event.target.checked ? null : (field.default ?? 0))
                  }
                />
                Automatic / none
              </span>
            )}
            {field.description && (
              <small id={`${id}-help`} className="pl-help">
                {field.description}
              </small>
            )}
          </label>
        );
      })}
    </>
  );
}
