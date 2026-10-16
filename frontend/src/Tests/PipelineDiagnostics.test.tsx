import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PipelineDiagnostics,
  type PipelineState,
} from "@/features/pipelines/PipelineDiagnostics";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
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
