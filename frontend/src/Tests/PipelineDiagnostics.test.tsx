import {
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  PipelineDiagnostics,
  type PipelineState,
} from "@/features/pipelines/PipelineDiagnostics";

const state = (): PipelineState => ({
  run_id: "run",
  revision_id: "revision",
  fingerprint: "fingerprint",
  captured_at: "2026-10-16T12:00:00Z",
  phase: "operational",
  sequence_number: 12,
  nodes: {
    scaler: {
      state: "ready",
      learn_count: 12,
      score_count: 10,
      learn_time_ns: 1_000_000,
      score_time_ns: 500_000,
      ready: true,
      learned_updates: null,
      readiness_observed: null,
      readiness_required: null,
      readiness_reason: null,
    },
  },
  observation: {
    sequence_number: 12,
    timestamp: "2026-10-16T12:00:00Z",
    phase: "operational",
    input_timestamps: { temperature: "2026-10-16T11:59:59Z" },
    passes: {
      score: {
        scaler: {
          input: { temperature: 25 },
          output: { temperature: 0.5 },
          state: "scored",
        },
      },
      learn: {
        scaler: {
          input: { temperature: 25 },
          output: { temperature: 0.45 },
          state: "learned",
        },
      },
    },
  },
  truncated: false,
  diagnostic_errors: 0,
});

describe("pipeline execution inspection", () => {
  it("keeps the learned reference requirement independent of the global warmup threshold", () => {
    const snapshot = state();
    snapshot.adaptive_learning = {
      state: "warmup",
      model_updates: 52,
      warmup_updates: 52,
      warmup_required: 50,
      ready: false,
      reason: "Retained history is not ready",
    };
    render(<PipelineDiagnostics state={snapshot} expectedRunId="run" />);
    const summary = within(
      screen.getByRole("region", { name: "Adaptive learning progress" }),
    );
    expect(summary.getByText("52 / 50")).toBeTruthy();
    expect(summary.getByText("No")).toBeTruthy();
    expect(summary.getByText("Retained history is not ready")).toBeTruthy();
  });
  it("presents static buffer counts separately from the frozen fitted baseline", () => {
    const snapshot = state();
    snapshot.batch_training = {
      state: "ready",
      training_samples: 0,
      calibration_samples: 0,
      frozen: true,
    };
    render(<PipelineDiagnostics state={snapshot} expectedRunId="run" />);
    const summary = within(
      screen.getByRole("region", { name: "Static fitting progress" }),
    );
    expect(summary.getAllByText("0")).toHaveLength(2);
    expect(summary.getByText("Yes")).toBeTruthy();
    expect(summary.getByText(/can reset after fitting/)).toBeTruthy();
  });
  it("shows readiness progress separately from observed calls and follows a blocked prerequisite", () => {
    const snapshot = state();
    Object.assign(snapshot.nodes.scaler!, {
      ready: false,
      learned_updates: 30,
      readiness_observed: 2,
      readiness_required: 50,
      readiness_reason: "Waiting for projection warmup",
      blocked_by: ["projection"],
    });
    const onSelect = vi.fn();
    render(
      <PipelineDiagnostics
        state={snapshot}
        selected="scaler"
        expectedRunId="run"
        nodeLabels={{ projection: "Online PCA" }}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText("2 / 50")).toBeTruthy();
    expect(screen.getByText("30")).toBeTruthy();
    expect(screen.getByText("Waiting for projection warmup")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect prerequisite Online PCA" }),
    );
    expect(onSelect).toHaveBeenCalledWith("projection");
  });
  it("omits learning updates until the runtime reports one", () => {
    const snapshot = state();
    render(<PipelineDiagnostics state={snapshot} selected="scaler" expectedRunId="run" />);
    expect(screen.queryByText("Successful learning updates")).toBeNull();
    expect(screen.queryByText(/include restored history/)).toBeNull();
  });
  it("does not interpret an unquantified minimum as ready", () => {
    const snapshot = state();
    Object.assign(snapshot.nodes.scaler!, {
      ready: false,
      readiness_observed: 0,
      readiness_required: 0,
    });
    render(
      <PipelineDiagnostics
        state={snapshot}
        selected="scaler"
        expectedRunId="run"
      />,
    );
    expect(screen.getByText("0 · minimum not quantified")).toBeTruthy();
    expect(screen.getByText("No")).toBeTruthy();
  });
  it("keeps before-learning and learning previews within the same observation", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-16T12:00:04Z"));
    render(
      <PipelineDiagnostics
        state={state()}
        selected="scaler"
        expectedRunId="run"
      />,
    );
    expect(screen.getByText("0.5000000")).toBeTruthy();
    expect(screen.queryByText("0.4500000")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Learning pass" }));
    expect(screen.getByText("0.4500000")).toBeTruthy();
    expect(screen.queryByText("0.5000000")).toBeNull();
    expect(screen.getByText(/Sampled observation 12/)).toBeTruthy();
  });
  it("rejects a snapshot from another run instead of applying stale component values", () => {
    render(
      <PipelineDiagnostics
        state={state()}
        selected="scaler"
        expectedRunId="successor"
      />,
    );
    expect(screen.getByText(/Waiting for a runtime snapshot/)).toBeTruthy();
    expect(screen.queryByText("0.5000000")).toBeNull();
  });
});
