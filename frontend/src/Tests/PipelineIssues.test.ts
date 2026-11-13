import { describe, expect, it } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { openSummary, showIssues } from "@/features/pipelines/issues";
import type { GraphDocument } from "@/features/pipelines/model";
import type * as Wire from "@/types/pipelines.generated";
import { groupOf } from "./support/fixtures/pipelines";

const component = (id: string, kind: Wire.PipelineComponent["kind"], label: string): Wire.PipelineComponent => ({
  id, kind, group: groupOf(kind), label, description: "", learning: kind === "detector" ? "online" : "none", fields: [],
  input_type: kind === "source" ? null : kind === "calibration" ? "scores" : kind === "policy" ? "p_values"
    : kind === "output" ? "decisions" : "features",
  output_type: kind === "detector" ? "scores" : kind === "calibration" ? "p_values" : kind === "policy" ? "decisions"
    : kind === "output" ? "evidence" : "features",
});
const { components } = normalizeCatalog({
  catalog_id: "issues", authoring_enabled: true,
  components: [
    component("source.aligned", "source", "Aligned inputs"),
    component("features.passthrough", "transform", "Pass through"),
    component("features.merge", "merge", "Merge features"),
    component("detector:aberrant_x_stream", "detector", "xStream"),
    component("calibrate.fixed_split", "calibration", "Fixed split"),
    component("policy.quantile", "policy", "Calibrated score threshold"),
    component("sink.evidence", "output", "Evidence and alarms"),
  ],
  templates: [],
});

const STEPS: Record<string, Wire.PipelineNode> = {
  input: { id: "input", kind: "source", component: "source.aligned" },
  detector: { id: "detector", kind: "detector", component: "detector:aberrant_x_stream" },
  calibrate: { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
  policy: { id: "policy", kind: "policy", component: "policy.quantile" },
  output: { id: "output", kind: "output", component: "sink.evidence" },
  aside: { id: "aside", kind: "transform", component: "features.passthrough" },
  merge: { id: "merge", kind: "merge", component: "features.merge" },
};
const design = (ids: string[], edges: Array<[string, string]>, labels: Record<string, string> = {}): GraphDocument => ({
  definition: normalizeDefinition({
    schema_version: 2, input_slots: [{ id: "value", label: "Value" }],
    nodes: ids.map((id) => STEPS[id]!), edges: edges.map(([source, target]) => ({ source, target })),
  }),
  layout: normalizeLayout({ nodes: Object.fromEntries(ids.map((id, index) =>
    [id, { x: index * 288, y: 100, ...(labels[id] ? { label: labels[id] } : {}) }])) }),
});
const TAIL: Array<[string, string]> = [["calibrate", "policy"], ["policy", "output"]];
const complete = () => design(["input", "detector", "calibrate", "policy", "output"],
  [["input", "detector"], ["detector", "calibrate"], ...TAIL]);
const issue = (code: string, message: string, node_id?: string, severity?: "warning"): Wire.PipelineIssue =>
  ({ code, message, ...(node_id ? { node_id } : {}), ...(severity ? { severity } : {}) });
const unreached = (id: string) => issue("disconnected", "Every node must reach the evidence output", id);
const unfed = (id: string) => issue("input_count", "This node requires exactly one input", id);

describe("showIssues", () => {
  it("has nothing to say about a complete design", () => {
    expect(showIssues(complete(), components, [])).toEqual([]);
    expect(showIssues(complete(), components)).toEqual([]);
  });

  it("asks for the detector once, instead of faulting the steps on either side of its place", () => {
    const open = design(["input", "calibrate", "policy", "output"], TAIL);
    const shown = showIssues(open, components, [
      issue("node_count", "An executable design requires at least one detector node"),
      unreached("input"), unfed("calibrate"),
    ]);
    expect(shown).toEqual([{ tone: "open", message: "Choose a detector.", detector: true }]);
    expect(openSummary(shown)).toBe("Choose a detector");
  });

  it("names a step every design needs when it is missing", () => {
    const shown = showIssues(design(["input", "detector", "calibrate", "output"], [["input", "detector"], ["detector", "calibrate"]]),
      components, [issue("node_count", "An executable design requires exactly one policy node"), unreached("calibrate"), unfed("output")]);
    expect(shown[0]).toEqual({ tone: "open", message: "Add a Detection rule." });
    expect(shown.map((item) => item.tone)).toEqual(["open", "open", "open"]);
    expect(openSummary(shown)).toBe("3 things to finish");
  });

  it("keeps the compiler's own sentences when the missing steps cannot be told apart", () => {
    const shown = showIssues(complete(), components, [issue("node_count", "An executable design requires exactly one source node")]);
    expect(shown).toEqual([{ tone: "error", message: "An executable design requires exactly one source node", node_id: undefined }]);
  });

  it("says once, by its title, that a step is not connected yet", () => {
    const document = design(["input", "detector", "calibrate", "policy", "output", "aside"],
      [["input", "detector"], ["detector", "calibrate"], ...TAIL], { aside: "Raw copy" });
    const shown = showIssues(document, components, [unfed("aside"), unreached("aside")]);
    expect(shown).toEqual([{ tone: "open", node_id: "aside", message: "Raw copy is not connected yet.", short: "Not connected yet" }]);
    expect(openSummary(shown)).toBe("1 step to connect");
  });

  it("tells a step without an output from a step without an input", () => {
    const leading = design(["input", "detector", "calibrate", "policy", "output", "aside"],
      [["input", "detector"], ["detector", "calibrate"], ...TAIL, ["input", "aside"]]);
    expect(showIssues(leading, components, [unreached("aside")])).toEqual([
      { tone: "open", node_id: "aside", message: "Pass through leads nowhere yet. Connect its output.", short: "No output yet" }]);

    const waiting = design(["input", "detector", "calibrate", "policy", "output", "aside"],
      [["input", "detector"], ["aside", "detector"], ["detector", "calibrate"], ...TAIL]);
    expect(showIssues(waiting, components, [unfed("aside")])).toEqual([
      { tone: "open", node_id: "aside", message: "Pass through needs an input.", short: "No input yet" }]);
  });

  it("says what a merge step and a calibration step are waiting for", () => {
    const merging = design(["input", "merge", "detector", "calibrate", "policy", "output"],
      [["input", "merge"], ["merge", "detector"], ["detector", "calibrate"], ...TAIL]);
    expect(showIssues(merging, components, [issue("input_count", "A merge node requires at least two inputs", "merge")])[0])
      .toEqual(expect.objectContaining({ tone: "open", message: "Merge features needs at least two inputs." }));

    const uncalibrated = design(["input", "detector", "calibrate", "policy", "output"], [["input", "detector"], ...TAIL]);
    const shown = showIssues(uncalibrated, components, [unreached("detector"), unfed("calibrate")]);
    expect(shown.map((item) => item.message)).toEqual([
      "xStream leads nowhere yet. Connect its output.",
      "Fixed split needs a connection from the detector.",
    ]);
    expect(openSummary(shown)).toBe("2 steps to connect");
  });

  it("keeps an input count the step exceeds as a fault", () => {
    const doubled = design(["input", "aside", "detector", "calibrate", "policy", "output"],
      [["input", "aside"], ["input", "detector"], ["aside", "detector"], ["detector", "calibrate"], ...TAIL]);
    expect(showIssues(doubled, components, [unfed("detector")])).toEqual([
      { tone: "error", message: "This node requires exactly one input", node_id: "detector" }]);
  });

  it("passes warnings and unknown faults on, and drops what concerns a removed step", () => {
    const shown = showIssues(complete(), components, [
      issue("history", "A window of 5 learns little.", "detector", "warning"),
      issue("parameters", "K must be at least 1.", "detector"),
      issue("cycle", "The design contains a cycle."),
      unreached("removed"),
    ]);
    expect(shown).toEqual([
      { tone: "warning", message: "A window of 5 learns little.", node_id: "detector" },
      { tone: "error", message: "K must be at least 1.", node_id: "detector" },
      { tone: "error", message: "The design contains a cycle.", node_id: undefined },
    ]);
  });
});

describe("openSummary", () => {
  it("counts steps to add apart from steps to connect", () => {
    expect(openSummary([{ tone: "open", message: "Add a Detection rule." }])).toBe("1 step to add");
    expect(openSummary([{ tone: "open", message: "Choose a detector.", detector: true },
      { tone: "open", message: "Pass through is not connected yet.", node_id: "aside" }])).toBe("2 things to finish");
  });
});
