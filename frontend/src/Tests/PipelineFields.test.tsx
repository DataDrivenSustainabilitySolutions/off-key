import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { JsonValue } from "@/types/monitoring";
import {
  ParameterFields,
  type FieldDescriptor,
} from "@/features/pipelines/ParameterFields";

afterEach(cleanup);
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
