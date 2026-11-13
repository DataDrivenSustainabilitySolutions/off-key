import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JsonValue } from "@/types/monitoring";
import {
  ParameterFields,
  type FieldDescriptor,
} from "@/components/parameter-editor/ParameterFields";
function Fields({
  fields,
  initial = {},
}: {
  fields: FieldDescriptor[];
  initial?: Record<string, JsonValue>;
}) {
  const [values, setValues] = useState(initial);
  return (
    <>
      <ParameterFields
        fields={fields}
        values={values}
        features={["voltage", "temperature"]}
        onChange={setValues}
      />
      <output data-testid="params">{JSON.stringify(values)}</output>
    </>
  );
}
describe("bounded pipeline parameter controls", () => {
  it("gives repeated nested controls distinct label and help targets", () => {
    render(<Fields fields={[{ name: "items", label: "Items", type: "object_list",
      fields: [{ name: "count", label: "Count", type: "integer" }] }]}
      initial={{ items: [{ count: 1 }, { count: 2 }] }} />);
    const controls = screen.getAllByRole("spinbutton", { name: /^Count$/ });
    expect(new Set(controls.map(control => control.id)).size).toBe(2);
    controls.forEach(control => expect(document.getElementById(`${control.id}-description`)).toBeTruthy());
  });

  it("keeps omitted defaults distinct from explicit null and supports resetting", () => {
    render(<Fields fields={[{ name: "seed", label: "Seed", type: "integer",
      required: false, has_default: true, default: null, nullable: true }]} />);
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({});
    fireEvent.click(screen.getByRole("checkbox", { name: "Seed automatic" }));
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({ seed: 0 });
    fireEvent.click(screen.getByRole("checkbox", { name: "Seed automatic" }));
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({ seed: null });
    fireEvent.click(screen.getByRole("button", { name: "Use default" }));
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({});
  });

  it("shows independent nested errors once beside the affected fields", () => {
    render(<ParameterFields fields={[{ name: "engine", label: "Engine", type: "component",
      fields: [{ name: "k", label: "Neighbors", type: "integer" },
        { name: "window", label: "Window", type: "integer" }] }]}
      values={{ engine: { id: "faiss", params: { k: 0, window: 0 } } }}
      onChange={() => undefined}
      issues={[{ path: ["engine", "params", "k"], message: "Choose a positive count" },
        { path: ["engine", "params", "window"], message: "Choose a window" }]} />);
    expect(screen.getAllByText("Choose a positive count")).toHaveLength(1);
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    expect(screen.getByRole("spinbutton", { name: "Neighbors" }).getAttribute("aria-invalid")).toBe("true");
  });

  it("selects and explicitly orders named features without raw JSON editing", () => {
    render(
      <Fields
        fields={[
          { name: "features", label: "Keep features", type: "features" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "temperature" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "voltage" }));
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      features: ["temperature", "voltage"],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Move voltage earlier" }),
    );
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      features: ["voltage", "temperature"],
    });
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("edits semantic feature names and numeric pairs with concrete controls", () => {
    render(
      <Fields
        fields={[
          { name: "mapping", label: "Rename features", type: "rename" },
          {
            name: "feature_range",
            label: "Feature range",
            type: "number_pair",
            default: [0, 1],
          },
        ]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "temperature" }), {
      target: { value: "temperature_raw" },
    });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Feature range 2" }),
      { target: { value: "10" } },
    );
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      mapping: { temperature: "temperature_raw" },
      feature_range: [0, 10],
    });
  });

  it("switches discriminator variants and drops parameters from the previous kind", () => {
    render(
      <Fields
        initial={{ threshold: { mode: "manual", value: 100 } }}
        fields={[
          {
            name: "threshold",
            label: "Threshold",
            type: "object",
            discriminator: "mode",
            variants: {
              manual: [
                {
                  name: "value",
                  label: "Threshold value",
                  type: "number",
                  default: 100,
                },
              ],
              automatic: [
                {
                  name: "horizon",
                  label: "Horizon",
                  type: "integer",
                  default: 1000,
                },
              ],
            },
          },
        ]}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Threshold kind" }), {
      target: { value: "automatic" },
    });
    expect(
      screen.queryByRole("spinbutton", { name: "Threshold value" }),
    ).toBeNull();
    expect(screen.getByRole("spinbutton", { name: "Horizon" })).toBeTruthy();
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      threshold: { mode: "automatic", horizon: 1000 },
    });
  });

  it("preserves an explicit nullable choice instead of falling back to the catalog default", () => {
    render(
      <Fields
        fields={[
          {
            name: "seed",
            label: "Seed",
            type: "integer",
            nullable: true,
            default: 42,
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Seed automatic" }));
    expect(
      (screen.getByRole("spinbutton", { name: /Seed/ }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      seed: null,
    });
  });

  it("edits graph model adjacency using integer controls", () => {
    render(
      <Fields
        fields={[
          {
            name: "graph",
            label: "Graph",
            type: "integer_adjacency",
            default: null,
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Automatic graph" }));
    fireEvent.click(screen.getByRole("button", { name: "Add feature" }));
    fireEvent.click(screen.getByRole("button", { name: "Add neighbor" }));
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Graph feature 0 neighbor 1" }),
      { target: { value: "2" } },
    );
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({
      graph: { "0": [2] },
    });
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("what the catalog says about a step's settings", () => {
  const amount = (label: string, facts: Partial<FieldDescriptor> = {}): FieldDescriptor => ({
    name: label.toLowerCase().replace(/ /g, "_"), label, type: "integer", default: 1, has_default: true, ...facts,
  });
  const lesser = ["Leaf size", "Cache size", "Seed"].map((label) => amount(label, { advanced: true }));
  const more = () => screen.queryByText("More settings")?.closest("details");

  it("lists the key settings and keeps three or more lesser ones under More settings", () => {
    render(<Fields fields={[lesser[0]!, amount("Neighbors"), ...lesser.slice(1)]} />);
    expect(more()!.open).toBe(false);
    expect(more()!.contains(screen.getByLabelText("Neighbors"))).toBe(false);
    expect(lesser.every((field) => more()!.contains(screen.getByLabelText(field.label)))).toBe(true);
    // The key setting leads, whatever the order in the catalog.
    expect(screen.getAllByRole("group")[0]!.textContent).toMatch(/^Neighbors/);
  });

  it("lists one or two lesser settings with the others, and a step with no key setting in full", () => {
    const { unmount } = render(<Fields fields={[amount("Neighbors"), ...lesser.slice(0, 2)]} />);
    expect(more()).toBeUndefined();
    unmount();
    render(<Fields fields={lesser} />);
    expect(more()).toBeUndefined();
    expect(screen.getByLabelText("Seed")).toBeTruthy();
  });

  it("opens More settings where one of them was changed or is at fault, and stays as the operator left it", () => {
    const fields = [amount("Neighbors"), ...lesser];
    // A new step has every default written out, which changes nothing.
    const fresh = render(<Fields fields={fields} initial={{ neighbors: 5, leaf_size: 1, cache_size: 1, seed: 1 }} />);
    expect(more()!.open).toBe(false);
    fresh.unmount();
    const { unmount } = render(<Fields fields={fields} initial={{ seed: 7 }} />);
    expect(more()!.open).toBe(true);
    // Back at its default, the setting does not fold away under the operator.
    fireEvent.click(screen.getByRole("button", { name: "Use default" }));
    expect(JSON.parse(screen.getByTestId("params").textContent!)).toEqual({});
    expect(more()!.open).toBe(true);
    unmount();
    render(<ParameterFields fields={fields} values={{}} onChange={() => undefined}
      issues={[{ path: ["cache_size"], message: "Choose a positive size" }]} />);
    expect(more()!.open).toBe(true);
    expect(screen.getByRole("alert").textContent).toBe("Choose a positive size");
  });

  it("shows a setting only while the one it depends on calls for it", () => {
    const fields: FieldDescriptor[] = [
      { name: "method", label: "Method", type: "enum", default: "exponential", has_default: true,
        options: ["exponential", "rolling", "time_constant"] },
      amount("Window", { shown_when: { field: "method", not_equals: ["time_constant"] } }),
      amount("Time constant", { shown_when: { field: "method", equals: ["time_constant"] } }),
      // A condition on a setting that is not listed here leaves the setting in place.
      amount("Lag", { shown_when: { field: "mode", equals: ["lag"] } }),
    ];
    render(<Fields fields={fields} />);
    const listed = () => screen.getAllByRole("spinbutton").map((control) => control.id.replace("parameter-", ""));
    expect(listed()).toEqual(["window", "lag"]);
    fireEvent.change(screen.getByLabelText("Method"), { target: { value: JSON.stringify("time_constant") } });
    expect(listed()).toEqual(["time_constant", "lag"]);
  });
});
