import type { PipelineRunEventView } from "@/types/pipelines.generated";

export type TimelineTone = "neutral" | "positive" | "warning" | "danger";

export interface TimelineEntry {
  key: string;
  at: string;
  title: string;
  lines: string[];
  tone: TimelineTone;
}

const stages: Record<string, string> = {
  starting: "Starting",
  waiting_for_data: "Waiting for data",
  collecting_training: "Learning",
  collecting_calibration: "Calibrating",
  training: "Training",
  operational: "Active",
  degraded: "Degraded",
  failed: "Failed",
  stopped: "Stopped",
};

const setupPhases: Record<string, string> = {
  requested: "Setup requested",
  preflighting: "Checking the configuration",
  validated: "Configuration checked",
  retiring: "Stopping the previous service",
  starting: "Starting the worker",
  awaiting_heartbeat: "Waiting for the worker to connect",
  succeeded: "Setup finished",
  cancelling: "Cancelling setup",
  cancelled: "Setup cancelled",
  failed: "Setup failed",
};

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() ? value.trim() : undefined;
const count = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;
const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;

export function stageLabel(stage: string | null | undefined): string {
  return (stage && stages[stage]) || stage || "Unknown";
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest ? `${hours} h ${rest} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days} d ${hours % 24} h` : `${days} d`;
}

function stageLines(detail: Record<string, unknown>): string[] {
  const lines: string[] = [];
  const reason = text(detail.detail);
  if (reason) lines.push(reason);
  const previous = count(detail.previous_stage_seconds);
  const from = text(detail.from);
  if (from && previous !== undefined) lines.push(`After ${formatDuration(previous)} ${stageLabel(from).toLowerCase()}`);
  const progress = record(detail.progress);
  if (progress && count(progress.target)) lines.push(`${count(progress.current) ?? 0} of ${count(progress.target)} observations`);
  const threshold = count(detail.threshold);
  if (threshold !== undefined) lines.push(`Alarm threshold ${Number(threshold.toPrecision(4))}`);
  const batch = record(detail.batch_training);
  if (batch) lines.push(`Trained on ${count(batch.training_samples) ?? 0}, calibrated on ${count(batch.calibration_samples) ?? 0} observations`);
  const error = text(detail.error) ?? text(detail.training_error);
  if (error) lines.push(error);
  const failing = record(detail.failing_nodes);
  if (failing) {
    for (const [node, value] of Object.entries(failing)) {
      const nodeError = text(record(value)?.error);
      lines.push(nodeError ? `${node}: ${nodeError}` : `${node} failed`);
    }
  }
  return lines;
}

/** One readable row per event: what happened, then the facts that explain it. */
export function timelineEntry(event: PipelineRunEventView, index: number): TimelineEntry {
  const detail = event.detail ?? {};
  const base = { key: `${event.occurred_at}-${index}`, at: event.occurred_at };
  switch (event.kind) {
    case "activation_phase": {
      const error = text(detail.error);
      const failed = event.stage === "failed" || event.stage === "cancelling" && !!error;
      return { ...base, title: setupPhases[event.stage ?? ""] ?? `Setup: ${event.stage}`,
        lines: error ? [error] : [], tone: failed ? "danger" : event.stage === "succeeded" ? "positive" : "neutral" };
    }
    case "activation_error":
      return { ...base, title: "Setup step will be retried", lines: [text(detail.error) ?? ""].filter(Boolean), tone: "warning" };
    case "runtime_started": {
      const restored = detail.restored_from_checkpoint === true;
      const processed = count(detail.restored_processed_count);
      return { ...base, title: restored ? "Worker started from its saved state" : "Worker started",
        lines: restored && processed !== undefined ? [`Resumed after ${processed} processed observations`] : [], tone: "neutral" };
    }
    case "stage_changed":
      return { ...base, title: stageLabel(event.stage), lines: stageLines(detail),
        tone: event.stage === "failed" ? "danger" : event.stage === "degraded" ? "warning" : event.stage === "operational" ? "positive" : "neutral" };
    case "coverage_gap": {
      const lost = count(detail.new_losses) ?? 0;
      const reason = text(detail.last_gap_reason);
      return { ...base, title: lost === 1 ? "1 message may be missing" : `${lost} messages may be missing`,
        lines: reason ? [`Last reason: ${reason.replace(/_/g, " ")}`] : [], tone: "warning" };
    }
    case "workload_crashed": {
      const exit = count(detail.exit_code);
      return { ...base, title: "Worker crashed", tone: "danger",
        lines: [text(detail.error), text(detail.hint), exit !== undefined ? `Exit code ${exit}` : undefined].filter((line): line is string => !!line) };
    }
    case "run_failed":
      return { ...base, title: "Run failed", lines: [text(detail.error) ?? ""].filter(Boolean), tone: "danger" };
    case "run_ended":
      return { ...base, title: `Run ended: ${text(detail.status) ?? event.stage ?? "stopped"}`, lines: [], tone: "neutral" };
    default:
      return { ...base, title: event.kind.replace(/_/g, " "), lines: [], tone: "neutral" };
  }
}
