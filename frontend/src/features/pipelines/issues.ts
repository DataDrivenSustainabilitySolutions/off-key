import type { PipelineComponent, PipelineNode, PipelineValidation } from "./contracts";
import { detectorSlot } from "./detectorSlot";
import { detectorIds, nodeOptionLabeler, type GraphDocument } from "./model";
import { isWarning } from "./scope";

type Issue = PipelineValidation["issues"][number];

/**
 * How an issue reads. An error needs a fix and a warning is worth a look. A design that
 * is still being built is neither: a step to choose or connect is `open`, work that is
 * left to do and no fault.
 */
type IssueTone = "error" | "warning" | "open";

export type ShownIssue = {
  tone: IssueTone;
  message: string;
  /** The step to open for it. */
  node_id?: string;
  /** For the step's card, where the step itself is the subject. */
  short?: string;
  /** The design has no detector yet; choosing one settles this. */
  detector?: boolean;
};

/** The steps every design has once, and how to ask for one that is missing. */
const REQUIRED: Partial<Record<PipelineNode["kind"], string>> = {
  source: "Add an Input step.",
  calibration: "Add a Calibration step.",
  policy: "Add a Detection rule.",
  output: "Add an Evidence output.",
};

/**
 * The compiler's issues in the composer's words. The compiler stays the judge of what
 * blocks a design; this only says it the way the canvas shows it: steps by their titles,
 * and unfinished wiring as open work, one line per step. An issue it does not recognise
 * is shown as the compiler wrote it.
 */
export function showIssues(
  document: GraphDocument,
  components: PipelineComponent[],
  issues: Issue[] = [],
): ShownIssue[] {
  const { nodes, edges } = document.definition;
  const label = nodeOptionLabeler(document, components);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const slot = detectorSlot(document, components);
  const detectors = detectorIds(document.definition).length;
  const shown: ShownIssue[] = [];

  // The compiler counts the steps a design lacks without naming them, so they are read
  // off the design. When the counts differ, its own sentences are kept.
  const missing = Object.keys(REQUIRED).filter((kind) => !nodes.some((node) => node.kind === kind));
  const counted = issues.filter((issue) => issue.code === "node_count").length;
  const named = counted > 0 && counted === missing.length + (slot ? 1 : 0);
  if (named) {
    if (slot) shown.push({ tone: "open", message: "Choose a detector.", detector: true });
    for (const kind of missing) shown.push({ tone: "open", message: REQUIRED[kind as PipelineNode["kind"]]! });
  }

  const has = (id: string, code: string) => issues.some((issue) => issue.node_id === id && issue.code === code);
  /** Whether a step has fewer inputs than it needs, rather than too many. */
  const lacksInput = (node: PipelineNode) => {
    const incoming = edges.filter((edge) => edge.target === node.id).length;
    return incoming < (node.kind === "merge" ? 2 : node.kind === "calibration" ? Math.max(detectors, 1) : 1);
  };
  const wired = new Set<string>();
  for (const issue of issues) {
    const node = issue.node_id ? byId.get(issue.node_id) : undefined;
    // An issue about a step that has since been removed is out of date.
    if (issue.node_id && !node) continue;
    if (isWarning(issue)) {
      shown.push({ tone: "warning", message: issue.message, node_id: node?.id });
      continue;
    }
    if (issue.code === "node_count" && named) continue;
    if (node && (issue.code === "disconnected" || (issue.code === "input_count" && lacksInput(node)))) {
      if (wired.has(node.id)) continue;
      wired.add(node.id);
      // The empty detector slot already explains the steps on either side of it.
      const input = has(node.id, "input_count") && lacksInput(node) && !(slot && node.kind === "calibration");
      const output = has(node.id, "disconnected") && !(slot && node.id === slot.after);
      if (!input && !output) continue;
      const title = label(node);
      shown.push({
        tone: "open",
        node_id: node.id,
        ...(input && output ? { message: `${title} is not connected yet.`, short: "Not connected yet" }
          : output ? { message: `${title} leads nowhere yet. Connect its output.`, short: "No output yet" }
            : {
              short: "No input yet",
              message: node.kind === "merge" ? `${title} needs at least two inputs.`
                : node.kind === "calibration"
                  ? `${title} needs a connection from ${detectors > 1 ? "each detector" : "the detector"}.`
                  : `${title} needs an input.`,
            }),
      });
      continue;
    }
    shown.push({ tone: "error", message: issue.message, node_id: node?.id });
  }
  return shown;
}

/** What is left to do, for a status chip that has only open work to report. */
export function openSummary(open: ShownIssue[]) {
  if (open.length === 1) return open[0]!.detector ? "Choose a detector" : open[0]!.node_id ? "1 step to connect" : "1 step to add";
  return open.every((issue) => issue.node_id) ? `${open.length} steps to connect` : `${open.length} things to finish`;
}
