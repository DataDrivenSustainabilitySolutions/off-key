import type { PipelineDefinition } from "./contracts";

export type StartupPhase = {
  id: "preparing" | "learning" | "calibration";
  label: string;
  verb: string;
  observations: number;
};

/** What a service sees before it can raise its first alarm: Prepare windows filling,
 * as the last check counted them, then learning and calibration. Learned steps upstream
 * of the detector may need a few observations of their own first, so this is a lower bound. */
export function startupPhases(definition: PipelineDefinition, preparation = 0): StartupPhase[] {
  const { training_window_size: learning, calibration_window_size: calibration } = definition.settings;
  const adaptive = definition.strategy === "adaptive_stream";
  return [
    ...(preparation > 0 ? [{ id: "preparing", label: "Preparing", verb: "prepare", observations: preparation } as const] : []),
    { id: "learning", label: adaptive ? "Detector learning" : "Training", verb: adaptive ? "learn" : "train", observations: learning },
    { id: "calibration", label: "Calibration", verb: "calibrate", observations: calibration },
  ];
}

/** Seconds between observations. An observation needs a new value from every reading,
 * so the slowest reading paces them; unknown while any reading has no measured interval. */
export function observationSeconds(intervals: ReadonlyArray<number | null | undefined>) {
  if (!intervals.length) return undefined;
  let slowest = 0;
  for (const interval of intervals) {
    if (typeof interval !== "number" || !Number.isFinite(interval) || interval <= 0) return undefined;
    slowest = Math.max(slowest, interval);
  }
  return slowest;
}

/** A readable duration for an estimate: "0.5 s", "45 s", "26 min", "2 h 10 min", "30 h", "3 days". */
export function roughDuration(seconds: number) {
  if (seconds < 10) return `${Number(seconds.toPrecision(2))} s`;
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  if (minutes < 600) return minutes % 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes / 60} h`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

export type Startup = {
  phases: StartupPhase[];
  observations: number;
  /** Seconds between observations, when every reading has a measured interval. */
  interval?: number;
  /** A Gate holds back observations its condition rejects, and they do not count, so the
   * start can take longer than these numbers. */
  gated?: boolean;
};

export function startupEstimate(
  definition: PipelineDefinition,
  intervals: ReadonlyArray<number | null | undefined>,
  preparation = 0,
): Startup {
  const phases = startupPhases(definition, preparation);
  return {
    phases,
    observations: phases.reduce((total, phase) => total + phase.observations, 0),
    interval: observationSeconds(intervals),
    gated: definition.nodes.some((node) => node.component === "prepare.gate"),
  };
}

export const observationCount = (observations: number) =>
  `${observations.toLocaleString()} ${observations === 1 ? "observation" : "observations"}`;

/** "≈ 26 min" with an interval, otherwise the observation count; "≥" when a Gate can make it longer. */
export const startupSummary = ({ observations, interval, gated }: Startup) =>
  interval ? `${gated ? "≥" : "≈"} ${roughDuration(observations * interval)}`
    : `${gated ? "≥ " : ""}${observationCount(observations)}`;

/** The estimate in one sentence, for the status popover and accessible names. */
export function startupSentence(startup: Startup) {
  const items = startup.phases.map((phase) => `${phase.observations.toLocaleString()} to ${phase.verb}`);
  const parts = items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items.join("");
  const time = startup.interval
    ? ` At one observation every ${roughDuration(startup.interval)}, that is about ${roughDuration(startup.observations * startup.interval)}.`
    : "";
  const gated = startup.gated
    ? " A Gate holds back the observations its condition rejects, and they do not count, so it can take longer."
    : "";
  return `The first alarm can come after at least ${observationCount(startup.observations)}: ${parts}.${time}${gated}`;
}
