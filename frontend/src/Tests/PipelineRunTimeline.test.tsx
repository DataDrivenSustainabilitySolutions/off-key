import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { pipelinesApi } from "@/features/pipelines/api";
import { PipelineRunTimeline } from "@/features/pipelines/PipelineRunTimeline";
import { formatDuration, timelineEntry } from "@/features/pipelines/timeline";
import type { PipelineRunEventView, PipelineRunTimeline as Timeline } from "@/types/pipelines.generated";

vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { timeline: vi.fn() } }));

const event = (kind: string, stage: string | null, detail: Record<string, unknown> = {}, at = "2026-11-03T10:00:00Z"): PipelineRunEventView =>
  ({ occurred_at: at, source: kind.startsWith("activation") || kind.startsWith("workload") || kind === "run_ended" ? "tactic" : "radar", kind, stage, detail });

const timeline = (events: PipelineRunEventView[], extra: Partial<Timeline> = {}): Timeline => ({
  run_id: "run-1", monitor_id: "svc-1", status: "running", created_at: "2026-11-03T09:59:00Z", events, ...extra,
});

describe("run timeline entries", () => {
  it("explains a stage change with its duration, threshold and training sizes", () => {
    const entry = timelineEntry(event("stage_changed", "operational", {
      from: "training", previous_stage_seconds: 754, threshold: 0.0123456,
      batch_training: { state: "frozen", training_samples: 1200, calibration_samples: 360, frozen: true },
    }), 0);
    expect(entry).toMatchObject({ title: "Active", tone: "positive" });
    expect(entry.lines).toEqual([
      "After 13 min training", "Alarm threshold 0.01235", "Trained on 1200, calibrated on 360 observations",
    ]);
  });

  it("names a crash, its out-of-memory hint and the failing node of a degraded stage", () => {
    expect(timelineEntry(event("workload_crashed", null, {
      error: "task: non-zero exit (137)", hint: "Killed by SIGKILL, usually for exceeding its memory limit", exit_code: 137,
    }), 0)).toMatchObject({ title: "Worker crashed", tone: "danger",
      lines: ["task: non-zero exit (137)", "Killed by SIGKILL, usually for exceeding its memory limit", "Exit code 137"] });
    expect(timelineEntry(event("stage_changed", "degraded", {
      detail: "Stale monitored inputs: phase_a", failing_nodes: { scaler: { state: "failed", error: "non-finite input" } },
    }), 0)).toMatchObject({ tone: "warning", lines: ["Stale monitored inputs: phase_a", "scaler: non-finite input"] });
  });

  it("reads setup phases, gaps and unknown kinds without raw identifiers", () => {
    expect(timelineEntry(event("activation_phase", "awaiting_heartbeat", { from: "starting" }), 0).title)
      .toBe("Waiting for the worker to connect");
    expect(timelineEntry(event("coverage_gap", "operational", { new_losses: 3, last_gap_reason: "queue_full" }), 0))
      .toMatchObject({ title: "3 messages may be missing", lines: ["Last reason: queue full"] });
    expect(timelineEntry(event("future_kind", null), 0).title).toBe("future kind");
  });

  it("formats durations at a readable precision", () => {
    expect([42, 600, 5400, 90000].map(formatDuration)).toEqual(["42 s", "10 min", "1 h 30 min", "1 d 1 h"]);
  });
});

describe("run timeline", () => {
  beforeEach(() => vi.resetAllMocks());

  it("loads only when opened and lists the newest event first", async () => {
    vi.mocked(pipelinesApi.timeline).mockResolvedValue(timeline([
      event("runtime_started", "starting", {}, "2026-11-03T10:00:00Z"),
      event("stage_changed", "collecting_training", { from: "starting" }, "2026-11-03T10:00:05Z"),
    ]));
    render(<PipelineRunTimeline serviceId="svc-1" />);
    expect(pipelinesApi.timeline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Run timeline"));
    const list = await screen.findByRole("list");
    expect(within(list).getAllByRole("listitem").map((item) => item.querySelector("strong")?.textContent))
      .toEqual(["Learning", "Worker started"]);
    expect(pipelinesApi.timeline).toHaveBeenCalledWith("svc-1", expect.any(AbortSignal));
  });

  it("opens a failed run with its final error and refreshes on request", async () => {
    vi.mocked(pipelinesApi.timeline).mockResolvedValue(timeline(
      [event("run_failed", "failed", { error: "Detector produced NaN" })],
      { status: "failed", error: "Detector produced NaN", ended_at: "2026-11-03T11:00:00Z" },
    ));
    render(<PipelineRunTimeline serviceId="svc-1" failed />);
    expect((await screen.findByText(/with: Detector produced NaN/)).textContent).toMatch(/^Ended /);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => expect(pipelinesApi.timeline).toHaveBeenCalledTimes(2));
  });

  it("shows a load failure in place", async () => {
    vi.mocked(pipelinesApi.timeline).mockRejectedValue(new Error("Monitoring service is unavailable (reference ab-1)"));
    render(<PipelineRunTimeline serviceId="svc-1" failed />);
    expect((await screen.findByRole("alert")).textContent).toContain("reference ab-1");
  });
});
