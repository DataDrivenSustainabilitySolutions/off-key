import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  alarmBudget, BUDGET_PERIODS, budgetCount, budgetNumber, budgetPeriod, budgetSentence, budgetShare, scoresPerAlarm,
  withAlarmShare,
} from "@/features/pipelines/alarmBudget";
import { AlarmBudgetSetting } from "@/features/pipelines/AlarmBudgetSetting";
import { normalizeCatalog, normalizeDefinition, type PipelineNode } from "@/features/pipelines/contracts";
import type { GraphDocument } from "@/features/pipelines/model";
import type * as Wire from "@/types/pipelines.generated";
import { groupOf } from "./support/fixtures/pipelines";

const component = (id: string, kind: Wire.PipelineComponent["kind"], fields: Wire.ComponentField[] = [],
  facts: Partial<Wire.PipelineComponent> = {}): Wire.PipelineComponent =>
  ({ id, kind, group: groupOf(kind), label: id, description: "", fields, ...facts });
const alpha: Wire.ComponentField = { name: "alpha", label: "Target alarm rate", type: "number", default: 0.01, has_default: true };
const { components } = normalizeCatalog({
  catalog_id: "budget", authoring_enabled: true, templates: [],
  components: [
    component("source.aligned", "source"),
    component("detector:forest", "detector"),
    component("calibrate.fixed_split", "calibration", [], { coverage: "exchangeable" }),
    component("calibrate.aci", "calibration", [alpha], { coverage: "long_run" }),
    component("calibrate.bocpd", "calibration", [alpha], { coverage: "none" }),
    component("policy.quantile", "policy"),
    component("policy.exceedance", "policy"),
    component("policy.martingale", "policy"),
  ],
});

/** input → detector → calibration → rule, with 360 calibration observations. */
type Step = Pick<PipelineNode, "component"> & Partial<Pick<PipelineNode, "params">>;
const design = (calibration: Step, policy: Step): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "detector", kind: "detector", component: "detector:forest" },
      { id: "calibrate", kind: "calibration", ...calibration },
      { id: "policy", kind: "policy", ...policy },
    ],
    edges: [
      { source: "input", target: "detector", order: 0 },
      { source: "detector", target: "calibrate", order: 0 },
      { source: "calibrate", target: "policy", order: 0 },
    ],
    settings: { training_window_size: 1200, calibration_window_size: 360, seed: 42 },
  }),
  layout: { nodes: {} },
});
const adapting = (params: PipelineNode["params"] = {}, rule: PipelineNode["params"] = {}) =>
  design({ component: "calibrate.aci", params }, { component: "policy.exceedance", params: rule });
const frozen = (params: PipelineNode["params"] = {}) =>
  design({ component: "calibrate.fixed_split" }, { component: "policy.quantile", params });
const budgetOf = (document: GraphDocument) => alarmBudget(document.definition, components);
const params = (document: GraphDocument, id: string) => document.definition.nodes.find((node) => node.id === id)!.params;
const [hour, day, week] = BUDGET_PERIODS;

describe("the alarm budget of a design", () => {
  it("is the alarm rate of a calibration step that adapts, whether it is spelled out or not", () => {
    expect(budgetOf(adapting())).toEqual({ node: "calibrate", field: "alpha", share: 0.01, promise: "long_run", consecutive: 1 });
    expect(budgetOf(adapting({ alpha: 0.002 }, { consecutive: 3 })))
      .toEqual({ node: "calibrate", field: "alpha", share: 0.002, promise: "long_run", consecutive: 3 });
    expect(budgetOf(design({ component: "calibrate.bocpd" }, { component: "policy.exceedance" }))?.promise).toBe("none");
    // A rate out of range is the step's own error, not a budget.
    expect(budgetOf(adapting({ alpha: 0 }))).toBeUndefined();
  });

  it("is what the quantile of a fixed threshold leaves above it, and no less than the calibration scores can tell", () => {
    const some = budgetOf(frozen({ quantile: 0.99 }))!;
    expect(some).toMatchObject({ node: "policy", field: "quantile", promise: "exchangeable", consecutive: 1 });
    expect(some.share).toBeCloseTo(0.01, 12);
    expect(some.finest).toBeCloseTo(1 / 361, 12);
    // The largest of 360 scores is passed about once in 361.
    expect(budgetOf(frozen())!.share).toBeCloseTo(1 / 361, 12);
    expect(budgetOf(frozen({ quantile: 0.9999 }))!.share).toBeCloseTo(1 / 361, 12);
  });

  it("is nothing for a design without its last steps and for one that alarms on a conformal martingale", () => {
    expect(budgetOf(design({ component: "calibrate.fixed_split" }, { component: "policy.martingale" }))).toBeUndefined();
    const open = frozen();
    open.definition.nodes = open.definition.nodes.filter((node) => node.kind !== "policy");
    expect(budgetOf(open)).toBeUndefined();
  });

  it("is written back to the setting that holds it", () => {
    const rate = adapting({ alpha: 0.01, gamma: 0.02 });
    expect(params(withAlarmShare(rate, budgetOf(rate)!, 1 / 120_960), "calibrate")).toEqual({ alpha: 0.00000826720, gamma: 0.02 });
    const threshold = frozen();
    expect(params(withAlarmShare(threshold, budgetOf(threshold)!, 0.02), "policy")).toEqual({ quantile: 0.98 });
    // The threshold cannot lie above the largest calibration score.
    const loose = frozen({ quantile: 0.98 });
    expect(params(withAlarmShare(loose, budgetOf(loose)!, 0.0001), "policy")).toEqual({ quantile: 1 });
    expect(withAlarmShare(rate, budgetOf(rate)!, 0)).toBe(rate);
    expect(withAlarmShare(rate, budgetOf(rate)!, 1)).toBe(rate);
  });

  it("counts per period, in the shortest period that holds one", () => {
    expect(budgetCount(0.01, 5, hour)).toBeCloseTo(7.2, 12);
    expect(budgetShare(7.2, 5, hour)).toBeCloseTo(0.01, 12);
    expect(budgetPeriod(0.01, 5)).toBe(hour);
    expect(budgetPeriod(0.001, 60)).toBe(day);
    expect(budgetPeriod(1 / 120_960, 5)).toBe(week);
    // Less than one a week still reads per week.
    expect(budgetPeriod(1e-6, 60)).toBe(week);
    expect(budgetNumber(720 / 361)).toBe(2);
    expect(budgetNumber(288)).toBe(290);
    expect(scoresPerAlarm(0.01)).toBe(100);
    expect(scoresPerAlarm(0.7)).toBe(2);
  });

  it("says what it counts and how far it holds", () => {
    expect(budgetSentence(budgetOf(adapting())!, { interval: 5 })).toBe(
      "That is one score in 100 above the boundary, at one observation every 5 s. "
      + "While nothing is wrong, each is a false alarm. It holds over a long run, also when the readings drift.");
    expect(budgetSentence(budgetOf(adapting({}, { consecutive: 3 }))!, { interval: 5, gated: true })).toBe(
      "That is one score in 100 above the boundary, at one observation every 5 s. "
      + "An alarm takes 3 in a row, so alarms come less often. It holds over a long run, also when the readings drift. "
      + "A Gate holds back observations, so there can be fewer.");
    expect(budgetSentence(budgetOf(frozen())!, { interval: 1 })).toBe(
      "That is one score in 361 above the boundary, at one observation every 1 s. "
      + "While nothing is wrong, each is a false alarm. It holds while the readings behave as they did during calibration. "
      + "Fewer alarms need more calibration observations.");
    expect(budgetSentence(budgetOf(design({ component: "calibrate.bocpd" }, { component: "policy.exceedance" }))!)).toBe(
      "A count per hour appears once the chosen readings report how often they arrive. "
      + "While nothing is wrong, each is a false alarm. The method aims at it without a guarantee.");
    // A window too short for the budget cannot keep it, which the check says itself.
    expect(budgetSentence(budgetOf(adapting({ alpha: 1e-5 }))!, { interval: 5, short: true })).toBe(
      "That is one score in 100,000 above the boundary, at one observation every 5 s. "
      + "While nothing is wrong, each is a false alarm.");
  });
});

describe("the alarm budget setting", () => {
  const changed = vi.fn();
  function Setting({ start, interval, shortfall, readOnly = false }: {
    start: GraphDocument; interval?: number; shortfall?: string; readOnly?: boolean;
  }) {
    const [document, setDocument] = useState(start);
    return <AlarmBudgetSetting document={document} components={components} interval={interval} shortfall={shortfall}
      readOnly={readOnly} onChange={(next, history) => { changed(params(next, "calibrate"), params(next, "policy"), history); setDocument(next); }} />;
  }
  const field = () => screen.getByRole<HTMLInputElement>("spinbutton", { name: "Alarm budget" });
  const period = () => screen.getByRole<HTMLSelectElement>("combobox", { name: "Budget period" });
  const type = (value: string) => fireEvent.change(field(), { target: { value } });

  it("reads and sets the budget as a count in a period, and keeps what was typed", () => {
    changed.mockClear();
    render(<Setting start={adapting()} interval={5} />);
    expect(field().value).toBe("7.2");
    expect(period().value).toBe("hour");

    type("12.5");
    expect(changed).toHaveBeenLastCalledWith({ alpha: 0.0173611 }, {}, "setting:budget");
    fireEvent.blur(field());
    // 12.5 an hour is the design's budget, so it stays as typed and is not rounded to 13.
    expect(field().value).toBe("12.5");
    expect(screen.getByText(/That is one score in 58 above the boundary/)).toBeTruthy();

    // Another period shows the same budget and changes nothing.
    changed.mockClear();
    fireEvent.change(period(), { target: { value: "day" } });
    expect(field().value).toBe("300");
    expect(changed).not.toHaveBeenCalled();
  });

  it("keeps the period while a number is typed that would read better in another", () => {
    render(<Setting start={adapting()} interval={5} />);
    type("0.5");
    expect(period().value).toBe("hour");
    expect(field().value).toBe("0.5");
    fireEvent.blur(field());
    expect(period().value).toBe("hour");
    expect(field().value).toBe("0.5");
  });

  it("keeps the last valid budget while the typed one cannot be", () => {
    changed.mockClear();
    render(<Setting start={adapting()} interval={5} />);
    type("0");
    expect(screen.getByText("Use a number above 0. The last valid value is kept.")).toBeTruthy();
    type("720");
    expect(screen.getByText("Use fewer than 720, which is every score. The last valid value is kept.")).toBeTruthy();
    type("");
    expect(screen.getByText("Enter a number. The last valid value is kept.")).toBeTruthy();
    expect(field().getAttribute("aria-invalid")).toBe("true");
    expect(changed).not.toHaveBeenCalled();
    fireEvent.blur(field());
    expect(field().value).toBe("7.2");
    expect(field().getAttribute("aria-invalid")).toBe("false");
  });

  it("goes no lower than the largest calibration score allows", () => {
    changed.mockClear();
    render(<Setting start={frozen({ quantile: 0.98 })} interval={5} />);
    expect(field().value).toBe("14");
    type("0.1");
    expect(changed).toHaveBeenLastCalledWith({}, { quantile: 1 }, "setting:budget");
    expect(screen.getByText(/Fewer alarms need more calibration observations\./)).toBeTruthy();
    fireEvent.blur(field());
    // 720 observations an hour, one in 361 above the largest calibration score.
    expect(field().value).toBe("2");
  });

  it("reads as one score in so many until the readings report how often they arrive", () => {
    changed.mockClear();
    render(<Setting start={adapting()} />);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(field().value).toBe("100");
    expect(screen.getByText("1 in")).toBeTruthy();
    expect(screen.getByText("scores")).toBeTruthy();
    type("250");
    expect(changed).toHaveBeenLastCalledWith({ alpha: 0.004 }, {}, "setting:budget");
    type("2.5");
    expect(screen.getByText("Enter a whole number. The last valid value is kept.")).toBeTruthy();
    type("1");
    expect(screen.getByText("Use at least 2. The last valid value is kept.")).toBeTruthy();
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("says what the check says about a calibration window too short for the budget", () => {
    const shortfall = "An alarm rate of 0.00001 needs at least 99,999 calibration observations; the calibration window has 360.";
    render(<Setting start={adapting({ alpha: 1e-5 })} interval={5} shortfall={shortfall} />);
    expect(screen.getByRole("status").textContent).toBe(shortfall);
    expect(screen.queryByText(/It holds over a long run/)).toBeNull();
  });

  it("can be read in any period but not set by someone who may not change the design", () => {
    changed.mockClear();
    render(<Setting start={adapting()} interval={5} readOnly />);
    expect(field().disabled).toBe(true);
    fireEvent.change(period(), { target: { value: "week" } });
    expect(field().value).toBe("1200");
    expect(changed).not.toHaveBeenCalled();
  });

  it("is absent where a design has no share of scores to set", () => {
    const { container } = render(<Setting start={design({ component: "calibrate.fixed_split" }, { component: "policy.martingale" })} interval={5} />);
    expect(container.innerHTML).toBe("");
  });
});
