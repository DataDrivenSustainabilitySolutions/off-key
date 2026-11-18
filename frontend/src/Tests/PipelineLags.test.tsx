import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizeDefinition, type PipelineComponent, type PipelineNode } from "@/features/pipelines/contracts";
import { PipelineLags } from "@/features/pipelines/PipelineLags";
import { PipelineScope } from "@/features/pipelines/PipelineScope";
import { defaultSuffix, lagText, parseLags, stepScope } from "@/features/pipelines/scope";
import { stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const lags = {
  id: "prepare.lags", kind: "transform", group: "prepare", label: "Lags", description: "",
  input_type: "features", output_type: "features",
  fields: [
    { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
    { name: "result", label: "Result", type: "enum", default: "add", has_default: true, options: ["add"] },
    { name: "suffix", label: "Suffix", type: "string", default: null, has_default: true, nullable: true },
    { name: "unit", label: "Unit", type: "enum", default: "minutes", has_default: true,
      options: ["observations", "seconds", "minutes", "hours", "days"] },
    { name: "lags", label: "Lags", type: "number_list", default: [1, 5, 15], has_default: true },
  ] as Field[],
} as PipelineComponent;
const node = (params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "lags", kind: "transform", component: "prepare.lags", params });

describe("Lags", () => {
  it("reads lags as people write them and writes them back short", () => {
    expect(parseLags("1-3, 24")).toEqual({ lags: [1, 2, 3, 24] });
    expect(parseLags("24 1 - 3 2")).toEqual({ lags: [1, 2, 3, 24] });
    expect(parseLags("1..4;8")).toEqual({ lags: [1, 2, 3, 4, 8] });
    expect(parseLags("")).toEqual({ error: "Write at least one lag." });
    expect(parseLags("0")).toEqual({ error: "Lags run from 1 to 3600 observations." });
    expect(parseLags("3-1")).toEqual({ error: "Write the range 3-1 from small to large." });
    expect(parseLags("1-30")).toEqual({ error: "At most 24 lags fit in one step." });
    expect(parseLags("a")).toHaveProperty("error");
    expect(lagText([1, 2, 3, 24])).toBe("1-3, 24");
    expect(lagText([1, 2, 5])).toBe("1, 2, 5");
  });

  it("names one feature per lag and feature, as core does", () => {
    expect(defaultSuffix(node(), lags)).toBe("lag");
    expect(stepScope(node({ lags: [24, 1], unit: "observations" }), lags)?.endings).toEqual(["lag1", "lag24"]);
    expect(stepScope(node({ suffix: "back" }), lags)?.endings).toEqual(["back1min", "back5min", "back15min"]);
    expect(stepScope(node({ lags: [24], unit: "hours" }), lags)?.endings).toEqual(["lag24h"]);
    const definition = normalizeDefinition({ input_slots: [{ id: "power", label: "Power" }], nodes: [] });
    expect(nodeSummary(node({ apply_to: ["power"], lags: [1, 24], unit: "observations" }), lags, definition)).toMatchObject({
      text: "Lags 1, 24 observations back", chips: ["+ power_lag1", "+ power_lag24"],
    });
    expect(nodeSummary(node({ apply_to: ["power"], lags: [1, 2, 3], unit: "hours" }), lags, definition)).toMatchObject({
      text: "Lags 1-3 h back", chips: ["+ power_lag1h", "+ power_lag2h", "+ power_lag3h"],
    });
    // The lags have their own control, so the generic settings leave them out.
    expect(stepFields(node(), lags).map((field) => field.name)).toEqual([]);
  });

  it("sets lags from text or a preset and leaves the default out", () => {
    const changes: Record<string, JsonValue>[] = [];
    const counted = { unit: "observations" };
    const { rerender } = render(<PipelineLags node={node(counted)} component={lags} issues={[]}
      onChange={(params) => { changes.push(params); }} />);
    const input = screen.getByRole("textbox", { name: "Lags" }) as HTMLInputElement;
    expect(input.value).toBe("1, 5, 15");
    fireEvent.change(input, { target: { value: "1-3, 2" } });
    expect(changes[changes.length - 1]).toEqual({ ...counted, lags: [1, 2, 3] });
    fireEvent.change(input, { target: { value: "1-3, x" } });
    expect(screen.getByRole("alert").textContent).toContain('"x" is not a lag');
    rerender(<PipelineLags node={node({ ...counted, lags: [1, 2, 3, 24] })} component={lags} issues={[]}
      onChange={(params) => { changes.push(params); }} />);
    // What is typed and invalid stays until it is fixed or left.
    expect(input.value).toBe("1-3, x");
    fireEvent.blur(input);
    expect(input.value).toBe("1-3, 24");
    expect(screen.getByText(/from the 25th observation on/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "1-6" }));
    expect(changes[changes.length - 1]).toEqual({ ...counted, lags: [1, 2, 3, 4, 5, 6] });
    fireEvent.change(screen.getByRole("combobox", { name: "Count lags in" }), { target: { value: "minutes" } });
    expect(changes[changes.length - 1]).toEqual({ lags: [1, 2, 3, 24] });
  });

  it("says how closely a lag in time finds its value", () => {
    render(<PipelineLags node={node({ lags: [24], unit: "hours" })} component={lags} issues={[]} onChange={() => undefined} />);
    expect(screen.getByText(/such as 24 h within 14 min/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "1, 6, 24" })).toBeTruthy();
  });

  it("shows no Result choice for a step that can only add", () => {
    render(<PipelineScope node={node({ apply_to: ["power"], lags: [1, 24], unit: "observations" })} component={lags}
      features={["power", "voltage"]} featureLabels={{}} issues={[]} onChange={() => undefined} />);
    expect(screen.queryByRole("group", { name: "Result" })).toBeNull();
    expect(screen.getByText("Keeps the values and adds power_lag1 and power_lag24.")).toBeTruthy();
    expect(screen.getByText(/such as feature_lag1/)).toBeTruthy();
  });
});
