import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  normalizeDefinition,
  type PipelineComponent,
  type PipelineNode,
} from "@/features/pipelines/contracts";
import { rejectionSummary } from "@/features/pipelines/diagnostics";
import { rangeText } from "@/features/pipelines/features";
import { PipelineTime } from "@/features/pipelines/PipelineTime";
import { defaultSuffix, hasScope } from "@/features/pipelines/scope";
import { stepDescription, stepFamily, stepFields } from "@/features/pipelines/steps";
import { nodeSummary } from "@/features/pipelines/summaries";
import type { JsonValue } from "@/types/monitoring";

type Field = PipelineComponent["fields"][number];
const flag = (name: string, label: string, value = false): Field =>
  ({ name, label, type: "boolean", default: value, has_default: true });
const step = (id: string, fields: Field[]): PipelineComponent => ({
  id, kind: "transform", label: id, description: "", input_type: "features", output_type: "features", fields,
});
const time = step("prepare.time", [
  flag("elapsed", "Seconds since the previous observation", true),
  flag("hour", "Hour of day"),
  flag("weekday", "Day of week"),
  flag("daily_cycle", "Daily cycle"),
  flag("weekly_cycle", "Weekly cycle"),
  { name: "timezone", label: "Time zone", type: "string", default: "UTC", has_default: true },
]);
const smooth = step("prepare.smooth", [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  { name: "result", label: "Result", type: "enum", default: "replace", has_default: true, options: ["replace", "add"] },
  { name: "suffix", label: "Suffix", type: "string", default: null, has_default: true, nullable: true },
  { name: "method", label: "Method", type: "enum", default: "exponential", has_default: true,
    options: ["exponential", "rolling", "time_constant"] },
  { name: "window_size", label: "Window", type: "integer", default: 10, has_default: true },
  { name: "time_constant", label: "Time constant", type: "number", default: 60, has_default: true },
]);

const node = (component: PipelineComponent, params: PipelineNode["params"] = {}): PipelineNode =>
  ({ id: "step", kind: "transform", component: component.id, params });
const definition = normalizeDefinition({ input_slots: [{ id: "dc_voltage", label: "DC voltage" }], nodes: [] });
const summary = (component: PipelineComponent, params?: PipelineNode["params"]) =>
  nodeSummary(node(component, params), component, definition).text;

type Issue = { path: string[]; message: string };
function editor(params: PipelineNode["params"] = {}, issues: Issue[] = [], readOnly = false) {
  const changes: [Record<string, JsonValue>, string][] = [];
  render(<PipelineTime node={node(time, params)} component={time} issues={issues} readOnly={readOnly}
    onChange={(next, field) => { changes.push([next, field]); }} />);
  return changes;
}
const box = (name: RegExp) => screen.getByRole("checkbox", { name }) as HTMLInputElement;

describe("steps that read time, in the composer", () => {
  it("lists Time features with the Prepare steps and gives it its own controls", () => {
    expect(stepFamily("transform", "prepare.time")).toBe("prepare");
    expect(stepDescription(time)).toContain("seconds since the previous observation");
    expect(hasScope(time)).toBe(false);
    expect(stepFields(node(time), time)).toEqual([]);
  });

  it("shows a Smooth the setting its method reads", () => {
    const names = (params: PipelineNode["params"]) => stepFields(node(smooth, params), smooth).map((field) => field.name);
    expect(names({})).toEqual(["method", "window_size"]);
    expect(names({ method: "rolling" })).toEqual(["method", "window_size"]);
    expect(names({ method: "time_constant" })).toEqual(["method", "time_constant"]);
  });

  it("names what a Smooth by time constant adds after its seconds, as core does", () => {
    const suffix = (params: PipelineNode["params"]) => defaultSuffix(node(smooth, { method: "time_constant", ...params }), smooth);
    expect(suffix({})).toBe("smooth60s");
    expect(suffix({ time_constant: 2.5 })).toBe("smooth2p5s");
    expect(suffix({ time_constant: 0.125 })).toBe("smooth0p125s");
    expect(suffix({ time_constant: 86400 })).toBe("smooth86400s");
    expect(suffix({ time_constant: 100 })).toBe("smooth100s");
    expect(defaultSuffix(node(smooth, { time_constant: 5 }), smooth)).toBe("smooth10");
  });

  it("says on the card what the steps do", () => {
    expect(summary(time)).toBe("Adds dt");
    expect(summary(time, { hour: true, weekday: true })).toBe("Adds dt, hour and weekday · UTC");
    expect(summary(time, { elapsed: false, daily_cycle: true, timezone: "Europe/Berlin" }))
      .toBe("Adds hour_sin and hour_cos · Europe/Berlin");
    expect(summary(time, { hour: true, weekday: true, daily_cycle: true, weekly_cycle: true }))
      .toBe("Adds dt, hour, weekday and 4 more · UTC");
    expect(summary(time, { elapsed: false })).toBe("No time feature yet");
    expect(summary(smooth, { method: "time_constant" })).toBe("Time constant 60 s");
    expect(summary(smooth, { method: "time_constant", time_constant: 2.5 })).toBe("Time constant 2.5 s");
  });

  it("reads a range that starts just above 0 as above 0", () => {
    expect(rangeText(Number.MIN_VALUE, null)).toBe("above 0");
    expect(rangeText(Number.MIN_VALUE, 60)).toBe("above 0 to 60");
    expect(rangeText(null, -Number.MIN_VALUE)).toBe("below 0");
    expect(rangeText(-5, -1e-200)).toBe("-5 to below 0");
    expect(rangeText(1e-9, 1)).toBe("0.000000001 to 1");
    expect(rangeText(0, null)).toBe("at least 0");
  });

  it("counts observations that arrived out of order", () => {
    expect(rejectionSummary({ out_of_order: 2 })).toBe("Skipped 2 observations: 2 not later than the one before.");
  });
});

describe("the Time features editor", () => {
  it("offers each feature with its names and keeps the last choice", () => {
    const changes = editor();
    expect(screen.getAllByRole("checkbox").map((item) => (item as HTMLInputElement).checked))
      .toEqual([true, false, false, false, false]);
    expect(screen.getByText("hour_sin, hour_cos")).toBeTruthy();
    // dt is the only feature, so it cannot be switched off.
    expect(box(/Seconds since the previous observation/).disabled).toBe(true);
    expect(screen.getByText(/ready after two/)).toBeTruthy();
    // dt follows no clock, so no time zone is asked for.
    expect(screen.queryByRole("combobox", { name: "Time zone" })).toBeNull();
    fireEvent.click(box(/Hour of day/));
    expect(changes).toEqual([[{ hour: true }, "hour"]]);
  });

  it("leaves a setting out where it holds the default", () => {
    const changes = editor({ elapsed: false, hour: true, timezone: "Europe/Berlin" });
    expect(box(/Hour of day/).disabled).toBe(true);
    fireEvent.click(box(/Seconds since the previous observation/));
    fireEvent.click(box(/Weekly cycle/));
    expect(changes).toEqual([
      [{ hour: true, timezone: "Europe/Berlin" }, "elapsed"],
      [{ elapsed: false, hour: true, timezone: "Europe/Berlin", weekly_cycle: true }, "weekly_cycle"],
    ]);
  });

  it("asks for a time zone once the hour or the weekday is added", () => {
    const changes = editor({ weekday: true });
    const zone = screen.getByRole("combobox", { name: "Time zone" }) as HTMLInputElement;
    expect(zone.value).toBe("");
    expect(zone.placeholder).toBe("UTC");
    fireEvent.change(zone, { target: { value: "Europe/Berlin" } });
    fireEvent.change(zone, { target: { value: "UTC" } });
    fireEvent.change(zone, { target: { value: " " } });
    expect(changes).toEqual([
      [{ weekday: true, timezone: "Europe/Berlin" }, "timezone"],
      [{ weekday: true }, "timezone"],
      [{ weekday: true }, "timezone"],
    ]);
  });

  it("shows what the check says beside the setting it is about", () => {
    editor({ hour: true, timezone: "Mars/Olympus" }, [
      { path: ["timezone"], message: "Unknown time zone. Write a name such as Europe/Berlin, or UTC." },
      { path: ["elapsed"], message: "dt already arrives here. Rename that feature before this step." },
    ]);
    const zone = screen.getByRole("combobox", { name: "Time zone" });
    expect(zone.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByRole("alert").map((item) => item.textContent)).toEqual([
      "dt already arrives here. Rename that feature before this step.",
      "Unknown time zone. Write a name such as Europe/Berlin, or UTC.",
    ]);
  });

  it("changes nothing in a design that is only shown", () => {
    editor({ hour: true }, [], true);
    expect(screen.getAllByRole("checkbox").every((item) => (item as HTMLInputElement).disabled)).toBe(true);
    expect((screen.getByRole("combobox", { name: "Time zone" }) as HTMLInputElement).disabled).toBe(true);
  });
});
