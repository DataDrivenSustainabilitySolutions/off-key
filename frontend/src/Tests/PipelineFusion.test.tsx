import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  type PipelineComponent,
  type PipelineValidation,
} from "@/features/pipelines/contracts";
import { formatMonitoringObservationTooltip } from "@/features/charts/monitoring-tooltip";
import { featuresView } from "@/features/pipelines/features";
import { changeCalibration } from "@/features/pipelines/learning";
import {
  addDetector,
  connectNodes,
  detectorBlocker,
  detectorIds,
  incomingEdges,
  occupiedInput,
  removeNode,
  type GraphDocument,
} from "@/features/pipelines/model";
import { PipelineDiagnostics, type PipelineState } from "@/features/pipelines/PipelineDiagnostics";
import { PipelineFeatures } from "@/features/pipelines/PipelineFeatures";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { PipelineToolbox } from "@/features/pipelines/PipelineToolbox";
import { nodeSummary } from "@/features/pipelines/summaries";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

type Field = PipelineComponent["fields"][number];
const scoped: Field[] = [
  { name: "apply_to", label: "Applies to", type: "features", default: null, has_default: true, nullable: true },
  { name: "result", label: "Result", type: "enum", default: "replace", has_default: true, options: ["replace", "add"] },
];
const fusion: Field = {
  name: "fusion", label: "Combine detectors", type: "enum", default: "max", has_default: true, options: ["max", "mean"],
};
const quantile: Field = { name: "quantile", label: "Quantile", type: "number", default: 1, has_default: true };
const alpha: Field = { name: "alpha", label: "Alarm rate", type: "number", default: 0.01, has_default: true };
const component = (
  id: string, kind: PipelineComponent["kind"], fields: Field[] = [], label = id,
  learning: PipelineComponent["learning"] = "none",
): PipelineComponent => ({
  id, kind, label, description: "", fields, learning,
  input_type: kind === "source" ? null : kind === "calibration" ? "scores" : kind === "policy" ? "p_values"
    : kind === "output" ? "decisions" : "features",
  output_type: kind === "detector" ? "scores" : kind === "calibration" ? "p_values" : kind === "policy" ? "decisions"
    : kind === "output" ? "evidence" : "features",
});
const components = [
  component("source.aligned", "source", [], "Input"),
  component("prepare.smooth", "transform", scoped, "Smooth"),
  component("adaptive.standard_scaler", "transform", scoped, "Standard scaling", "online"),
  component("features.select", "transform", [], "Select"),
  component("detector:mahalanobis", "detector", [{ name: "window_size", label: "Window", type: "integer", default: 20, has_default: true }], "Mahalanobis", "online"),
  component("detector:knn", "detector", [], "Nearest neighbours", "online"),
  { ...component("calibrate.fixed_split", "calibration", [fusion], "Fixed split"), family: "conformal" as const, coverage: "exchangeable" as const },
  { ...component("calibrate.aci", "calibration", [alpha, fusion], "ACI"), family: "conformal" as const, coverage: "long_run" as const },
  { ...component("calibrate.bocpd", "calibration", [alpha, fusion], "BOCPD"), family: "bayesian" as const, coverage: "none" as const },
  component("policy.quantile", "policy", [quantile], "Quantile"),
  component("policy.martingale", "policy", [], "Martingale"),
  component("policy.exceedance", "policy", [], "Exceedance rule"),
  component("output.evidence", "output", [], "Evidence"),
];
const catalog = { catalog_id: "fusion", authoring_enabled: true, components, templates: [] } as never;

/** Readings a and b, scaled once and selected per detector, meeting at the calibration step. */
function design(detectors: 1 | 2 = 2, calibration: object = {}, policy: object = {}): GraphDocument {
  const nodes = [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "scale", kind: "transform", component: "adaptive.standard_scaler" },
    { id: "only_a", kind: "transform", component: "features.select", params: { features: ["a"] } },
    { id: "only_b", kind: "transform", component: "features.select", params: { features: ["b"] } },
    { id: "detector", kind: "detector", component: "detector:mahalanobis", params: { window_size: 30 } },
    ...(detectors === 2 ? [{ id: "detector_2", kind: "detector", component: "detector:knn" }] : []),
    { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split", params: calibration },
    { id: "policy", kind: "policy", component: "policy.quantile", params: policy },
    { id: "output", kind: "output", component: "output.evidence" },
  ];
  const edges = [
    { source: "input", target: "scale" },
    { source: "scale", target: "only_a" },
    { source: "scale", target: "only_b" },
    { source: "only_a", target: "detector" },
    { source: "detector", target: "calibrate", order: 0 },
    ...(detectors === 2
      ? [{ source: "only_b", target: "detector_2" }, { source: "detector_2", target: "calibrate", order: 1 }]
      : []),
    { source: "calibrate", target: "policy" },
    { source: "policy", target: "output" },
  ];
  return {
    definition: normalizeDefinition({
      input_slots: [{ id: "a", label: "Reading A" }, { id: "b", label: "Reading B" }],
      nodes: nodes as never,
      edges: edges as never,
    }),
    layout: normalizeLayout({ nodes: { detector: { x: 900, y: 0 } } }),
  };
}

const report = {
  features: {
    input: [{ name: "a", slots: ["a"] }, { name: "b", slots: ["b"] }],
    scale: [{ name: "a", slots: ["a"], previous: "input.a", steps: ["scale"] }, { name: "b", slots: ["b"], previous: "input.b", steps: ["scale"] }],
    only_a: [{ name: "a", slots: ["a"], previous: "scale.a", steps: ["scale"] }],
    only_b: [{ name: "b", slots: ["b"], previous: "scale.b", steps: ["scale"] }],
  },
  issues: [],
  valid: true,
} as unknown as PipelineValidation;

describe("combining detectors in the graph", () => {
  it("adds another detector like the selected one, on its input and into the calibration step", () => {
    const added = addDetector(design(1), "detector")!;
    const { definition, layout } = added.document;

    expect(added.id).toBe("detector_2");
    expect(definition.nodes.find((node) => node.id === "detector_2")).toMatchObject({
      kind: "detector", component: "detector:mahalanobis", params: { window_size: 30 },
    });
    expect(incomingEdges(definition, "detector_2").map((edge) => edge.source)).toEqual(["only_a"]);
    expect(incomingEdges(definition, "calibrate").map((edge) => [edge.source, edge.order]))
      .toEqual([["detector", 0], ["detector_2", 1]]);
    expect(incomingEdges(definition, "policy").map((edge) => edge.source)).toEqual(["calibrate"]);
    // Below the original, without covering it.
    expect(layout.nodes.detector_2!.x).toBe(900);
    expect(layout.nodes.detector_2!.y).toBeGreaterThan(0);
  });

  it("stops at four detectors and says why", () => {
    const third = addDetector(design(2), "detector")!.document;
    const document = addDetector(third, "detector")!.document;

    expect(detectorIds(document.definition)).toEqual(["detector", "detector_2", "detector_3", "detector_4"]);
    expect(detectorBlocker(document.definition)).toBe("A design combines at most 4 detectors.");
    expect(addDetector(document, "detector")).toBeUndefined();
  });

  it("lets the calibration step take one input per detector, and the detection rule one", () => {
    const { definition } = design(2);
    const loose = removeNode({ definition, layout: design().layout }, "detector_2").definition;
    const back = { ...loose, nodes: [...loose.nodes, { ...definition.nodes.find((node) => node.id === "detector_2")! }] };

    expect(occupiedInput(back, "calibrate")).toBeUndefined();
    expect(occupiedInput(back, "policy")).toMatchObject({ source: "calibrate" });
    const connected = connectNodes(back, "detector_2", "calibrate", components);
    expect(incomingEdges(connected, "calibrate").map((edge) => edge.source)).toEqual(["detector", "detector_2"]);
    // A detector's scores do not go into the detection rule.
    expect(connectNodes(back, "detector_2", "policy", components)).toBe(back);
    expect(incomingEdges(removeNode({ definition, layout: design().layout }, "detector").definition, "calibrate")
      .map((edge) => edge.source)).toEqual(["detector_2"]);
  });

  it("names how the calibration step combines on its card, only with several detectors", () => {
    const find = (id: string) => components.find((item) => item.id === id)!;
    const node = (document: GraphDocument, kind: string) => document.definition.nodes.find((item) => item.kind === kind)!;
    const summary = (document: GraphDocument, kind: string) =>
      nodeSummary(node(document, kind), find(node(document, kind).component), document.definition).text;

    expect(summary(design(2), "calibration")).toBe("Strongest of 2 detectors");
    expect(summary(design(2), "policy")).toBe("Above the calibration maximum");
    const average = design(2, { fusion: "mean" }, { quantile: 0.99 });
    expect(summary(average, "calibration")).toBe("Average of 2 detectors");
    expect(summary(average, "policy")).toBe("Above calibration quantile 0.99");
    expect(summary(design(1, { fusion: "mean" }), "calibration")).toBeUndefined();
  });

  it("names a changed alarm rate and a missing guarantee on the calibration card", () => {
    const find = (id: string) => components.find((item) => item.id === id)!;
    const adapting = (id: string, params: object) => {
      const document = design(2);
      const node = { ...document.definition.nodes.find((item) => item.kind === "calibration")!, component: id, params };
      return nodeSummary(node as never, find(id), document.definition).text;
    };

    expect(adapting("calibrate.aci", { alpha: 0.01, fusion: "max" })).toBe("Strongest of 2 detectors");
    expect(adapting("calibrate.aci", { alpha: 0.05, fusion: "mean" })).toBe("Average of 2 detectors · Alarm rate 0.05");
    expect(adapting("calibrate.bocpd", { alpha: 0.01 })).toBe("Strongest of 2 detectors · No guarantee");
  });

  it("counts a model's nested settings at their defaults as unchanged on its card", () => {
    const engine: Field = {
      name: "similarity_engine", label: "Similarity engine", type: "component", has_default: true,
      default: { id: "faiss", params: { warm_up: 20, window_size: 1000 } },
    };
    const knn = { ...components.find((item) => item.id === "detector:knn")!, fields: [engine] };
    const node = { id: "detector_2", kind: "detector" as const, component: "detector:knn",
      params: { similarity_engine: { id: "faiss", params: { warm_up: 20, window_size: 1000 } } } };

    expect(nodeSummary(node, knn, design(2).definition).text).toBeUndefined();
    const changed = { ...node, params: { similarity_engine: { id: "faiss", params: { warm_up: 50, window_size: 1000 } } } };
    expect(nodeSummary(changed, knn, design(2).definition).text).toBe("1 more setting");
  });

  it("keeps Combine detectors when the calibration method changes", () => {
    const aci = components.find((item) => item.id === "calibrate.aci")!;
    const changed = changeCalibration(design(2, { fusion: "mean" }).definition, "calibrate", aci, components);
    const calibration = changed.definition.nodes.find((node) => node.kind === "calibration")!;

    expect(calibration.component).toBe("calibrate.aci");
    expect(calibration.params.fusion).toBe("mean");
    expect(changed.definition.nodes.find((node) => node.kind === "policy")!.component).toBe("policy.exceedance");
  });
});

describe("the inspector", () => {
  it("offers Add another detector and selects the new one", () => {
    const onChange = vi.fn();
    const onSelect = vi.fn();
    render(<PipelineInspector document={design(1)} catalog={catalog} selected="detector" validation={report}
      onSelect={onSelect} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Add another detector" }));

    const next = onChange.mock.calls[0]![0] as GraphDocument;
    expect(detectorIds(next.definition)).toEqual(["detector", "detector_2"]);
    expect(onSelect).toHaveBeenCalledWith("detector_2");
  });

  it("shows Combine detectors on the calibration step only once there are two", () => {
    const { unmount } = render(<PipelineInspector document={design(1)} catalog={catalog} selected="calibrate"
      validation={report} onSelect={() => {}} onChange={() => {}} />);
    expect(screen.queryByText("Combine detectors")).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Combine/ })).toBeNull();
    unmount();

    const onChange = vi.fn();
    render(<PipelineInspector document={design(2)} catalog={catalog} selected="calibrate" validation={report}
      onSelect={() => {}} onChange={onChange} />);
    const group = screen.getByRole("group", { name: "Combine detectors" });
    expect(within(group).getByRole("button", { name: "Strongest" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/The most surprised detector decides/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Detectors" })).toBeTruthy();

    fireEvent.click(within(group).getByRole("button", { name: "Average" }));
    const changed = (onChange.mock.calls[0]![0] as GraphDocument).definition;
    expect(changed.nodes.find((node) => node.id === "calibrate")!.params.fusion).toBe("mean");
    expect(changed.nodes.find((node) => node.id === "policy")!.params.fusion).toBeUndefined();
  });

  it("changes the calibration method, says what it promises and moves the detection rule along", () => {
    const onChange = vi.fn();
    const { rerender } = render(<PipelineInspector document={design(2)} catalog={catalog} selected="calibrate"
      validation={report} onSelect={() => {}} onChange={onChange} />);
    const method = screen.getByRole("combobox", { name: "Calibration method" }) as HTMLSelectElement;
    expect(method.value).toBe("calibrate.fixed_split");
    expect([...method.querySelectorAll("optgroup")].map((group) => group.label)).toEqual(["Conformal", "Bayesian"]);
    expect(screen.getByText("Exact while data stays alike.")).toBeTruthy();

    fireEvent.change(method, { target: { value: "calibrate.bocpd" } });
    const changed = onChange.mock.calls[0]![0] as GraphDocument;
    expect(changed.definition.nodes.find((node) => node.id === "calibrate")!.component).toBe("calibrate.bocpd");
    expect(changed.definition.nodes.find((node) => node.id === "policy")!.component).toBe("policy.exceedance");
    rerender(<PipelineInspector document={changed} catalog={catalog} selected="calibrate"
      validation={report} onSelect={() => {}} onChange={onChange} />);
    expect(screen.getByText("No guarantee.")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("The detection rule is now Exceedance rule. Undo reverses this.");
  });

  it("offers every detection rule and marks the ones that do not fit the design", () => {
    const onChange = vi.fn();
    render(<PipelineInspector document={design(2)} catalog={catalog} selected="policy" validation={report}
      onSelect={() => {}} onChange={onChange} />);
    const rule = screen.getByRole("combobox", { name: "Detection rule" }) as HTMLSelectElement;
    expect([...rule.options].map((option) => option.textContent)).toEqual([
      "Quantile", "Martingale (does not fit this design)", "Exceedance rule (does not fit this design)",
    ]);
    fireEvent.change(rule, { target: { value: "policy.martingale" } });
    const changed = (onChange.mock.calls[0]![0] as GraphDocument).definition;
    expect(changed.nodes.find((node) => node.id === "policy")!.component).toBe("policy.martingale");
  });

  it("names the detectors in the add-step menu once", () => {
    render(<PipelineToolbox components={components} document={design(2)} onAdd={() => {}} onSelect={() => {}} />);
    expect(screen.getByText(/The 2 detectors, calibration step, detection rule and output are already in this pipeline/))
      .toBeTruthy();
    expect(screen.getByText(/A detector's settings can add another detector/)).toBeTruthy();
  });
});

describe("the Features view", () => {
  it("lists the features of the chosen detector", () => {
    expect(featuresView(design(2).definition, report).rows.map((row) => row.name)).toEqual(["a"]);
    expect(featuresView(design(2).definition, report, "detector_2").rows.map((row) => row.name)).toEqual(["b"]);

    render(<PipelineFeatures document={design(2)} components={components} report={report}
      onSelect={() => {}} onChange={() => {}} />);
    const group = screen.getByRole("group", { name: "Detector" });
    expect(within(group).getByRole("button", { name: "Mahalanobis" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("a", { selector: "code" })).toBeTruthy();

    fireEvent.click(within(group).getByRole("button", { name: "Nearest neighbours" }));
    expect(screen.getByText("b", { selector: "code" })).toBeTruthy();
    expect(screen.queryByText("a", { selector: "code" })).toBeNull();
  });

  it("opens on the selected detector and says when a Prepare step reaches another one", () => {
    render(<PipelineFeatures document={design(2)} components={components} report={report} selected="detector_2"
      onSelect={() => {}} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Nearest neighbours" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Add a step for b" }));
    // Prepare steps run before the shared scaling, so the first detector sees them too.
    expect(screen.getByText(/Prepare steps go before Standard scaling, so they also change what Mahalanobis receives/))
      .toBeTruthy();
  });
});

describe("each detector's part in a run", () => {
  const observed = (): PipelineState => ({
    run_id: "run", revision_id: "revision", fingerprint: "fingerprint", captured_at: new Date().toISOString(),
    phase: "operational", sequence_number: 40,
    nodes: Object.fromEntries(["detector", "detector_2", "policy"].map((id) => [id, {
      state: "ready", learn_count: 40, score_count: 30, learn_time_ns: 0, score_time_ns: 0, ready: true,
      learned_updates: null, readiness_observed: null, readiness_required: null, readiness_reason: null,
    }])),
    observation: {
      sequence_number: 40, timestamp: "2026-11-02T10:00:00Z", phase: "operational",
      input_timestamps: { a: "2026-11-02T10:00:00Z" },
      passes: {
        score: {
          detector: { input: { a: 0.4 }, output: 2.5, state: "ready" },
          detector_2: { input: { b: -1 }, output: 0.25, state: "ready" },
        },
        learn: {},
      },
      detectors: [
        { detector_id: "detector", score: 2.5, surprise: 0.95 },
        { detector_id: "detector_2", score: 0.25, surprise: 0.3 },
      ],
    },
    truncated: false, diagnostic_errors: 0,
  });

  it("lists every detector's score and surprise on the policy", () => {
    const onSelect = vi.fn();
    render(<PipelineDiagnostics state={observed()} selected="policy" policyId="policy" expectedRunId="run"
      nodeLabels={{ detector: "Mahalanobis", detector_2: "Nearest neighbours" }} onSelect={onSelect} />);

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(["Mahalanobis2.5000000.95", "Nearest neighbours0.25000000.3"]);
    fireEvent.click(screen.getByRole("button", { name: "Nearest neighbours" }));
    expect(onSelect).toHaveBeenCalledWith("detector_2");
  });

  it("lists them on the calibration step too, which the runtime reports with the detection rule", () => {
    render(<PipelineDiagnostics state={observed()} selected="calibrate" policyId="policy" calibrationId="calibrate"
      expectedRunId="run" nodeLabels={{ detector: "Mahalanobis", detector_2: "Nearest neighbours" }} />);
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
  });

  it("gives a detector's surprise beside its score", () => {
    render(<PipelineDiagnostics state={observed()} selected="detector" policyId="policy" expectedRunId="run" />);
    expect(screen.getByText(/Surprise 0.95: the share of this detector's calibration scores below its score/))
      .toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("names each detector's part in the chart tooltip", () => {
    const tooltip = formatMonitoringObservationTooltip(
      [{ seriesName: "Anomaly score", value: [Date.parse("2026-11-02T10:00:00Z"), 0.95], data: { observation: {
        sequenceNumber: 40, timeMs: Date.parse("2026-11-02T10:00:00Z"), value: 0.95, threshold: 0.9, alarmActive: true,
        logValue: null, isInfinite: false, inputTimestamps: { a: "2026-11-02T10:00:00Z" },
        detectors: [{ detector_id: "detector", score: 2.5, surprise: 0.95 }, { detector_id: "detector_2", score: 0.25, surprise: 0.3 }],
      } } }],
      [], (time) => new Date(time).toISOString(), (value) => String(value),
    );
    expect(tooltip?.split("\n")).toEqual(expect.arrayContaining([
      "Detector detector: surprise 0.95, score 2.5",
      "Detector detector_2: surprise 0.3, score 0.25",
    ]));
  });
});
