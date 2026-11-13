import type { PipelineComponent } from "@/features/pipelines/contracts";

type Kind = PipelineComponent["kind"];
type Group = PipelineComponent["group"];

const GROUPS: Record<Kind, Group> = {
  source: "input", transform: "prepare", merge: "route", detector: "detector",
  calibration: "calibration", policy: "policy", output: "output",
};

/** The group a hand-built step of this kind has, where the test does not depend on it.
 * A test about a step's place in the menu names the group itself, as the catalog does. */
export const groupOf = (kind: Kind): Group => GROUPS[kind];
