import type { JsonValue } from "@/types/monitoring";
import { fieldDefaults, type FieldDescriptor } from "@/components/parameter-editor/types";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { incomingEdges, nodeLabel, type GraphDocument } from "./model";
import { componentFor, shownComponent, switchedOff } from "./semantics";
import { sameSetting } from "./summaries";

/** How one step differs from what a service runs now: the running design lacks it, or holds it differently. */
export type StepChange = { kind: "new" | "changed"; detail: string };

/** How a design differs from the one a service runs now. */
export type DesignComparison = {
  /** The steps that differ, by id. A step that is the same is left out. */
  steps: Record<string, StepChange>;
  /** The titles of the steps the running design holds and this one lacks. */
  removed: string[];
  /** What differs beside the steps, a sentence each: whether alarms are raised, the readings taken in
   * and how long the design learns. */
  service: string[];
};

const SETTINGS = [
  ["training_window_size", "Training observations"],
  ["calibration_window_size", "Calibration observations"],
  ["seed", "Random seed"],
] as const;

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

/** A setting's value in a word or two, or nothing where it takes more than a line. */
function worded(value: JsonValue | undefined): string | undefined {
  if (value == null) return "none";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "number")
    return (Number.isInteger(value) ? value : Number(value.toPrecision(4))).toLocaleString();
  if (typeof value === "string") return value.replace(/_/g, " ") || "empty";
  if (Array.isArray(value) && value.every((item) => item === null || typeof item !== "object"))
    return value.length ? value.map(worded).join(", ") : "none";
}

function settingChange(label: string, before: JsonValue | undefined, after: JsonValue | undefined) {
  const [was, now] = [worded(before), worded(after)];
  return was && now ? `${label} ${now}, was ${was}` : `${label} changed`;
}

function settingChanges(before: PipelineNode, after: PipelineNode, component: PipelineComponent | undefined) {
  const fields: Pick<FieldDescriptor, "name" | "label">[] = component?.fields ?? [];
  const defaults = fieldDefaults(component?.fields ?? []);
  const [was, now] = [{ ...defaults, ...before.params }, { ...defaults, ...after.params }];
  // A setting the catalog does not describe still counts, under its own name.
  const named = new Set(fields.map((field) => field.name));
  const others = [...new Set([...Object.keys(was), ...Object.keys(now)])].filter((name) => !named.has(name));
  const titled = (name: string) => (name.charAt(0).toUpperCase() + name.slice(1)).replace(/_/g, " ");
  return [...fields, ...others.map((name) => ({ name, label: titled(name) }))]
    .filter((field) => !sameSetting(was[field.name], now[field.name]))
    .map((field) => settingChange(field.label, was[field.name], now[field.name]));
}

/** What a step takes from, looking through the steps that only this design holds. */
function sourcesThrough(document: GraphDocument, id: string, shared: ReadonlySet<string>, seen = new Set<string>()): string[] {
  return incomingEdges(document.definition, id).flatMap(({ source }) => {
    if (shared.has(source) || seen.has(source)) return [source];
    seen.add(source);
    return sourcesThrough(document, source, shared, seen);
  });
}

/** Both designs, the steps they share, and how to name a step of the running one. */
type Compared = {
  running: GraphDocument;
  design: GraphDocument;
  components: PipelineComponent[];
  shared: ReadonlySet<string>;
  titleOf: (id: string) => string;
};

function connectionChange({ running, design, shared, titleOf }: Compared, id: string): string | undefined {
  const was = incomingEdges(running.definition, id).map((edge) => edge.source);
  const now = sourcesThrough(design, id, shared);
  // A new step in front of this one is the change, and its own card says so.
  if (sameSetting(was, now)) return undefined;
  const gone = was.filter((source) => !shared.has(source));
  // A step that went leaves no card, so the step behind it says that it went.
  return gone.length && sameSetting(sourcesThrough(running, id, shared), now)
    ? `No longer follows ${gone.map(titleOf).join(" and ")}` : "Connected differently";
}

function stepChanges(compared: Compared, before: PipelineNode, after: PipelineNode): string[] {
  const { running, design, components } = compared;
  const [wasOff, isOff] = [switchedOff(running.layout, before), switchedOff(design.layout, after)];
  const changes: string[] = [];
  if (!!wasOff !== !!isOff) changes.push(isOff ? "Switched off" : "Switched on");
  else if (!wasOff && (before.component !== after.component || (before.contract_version ?? 1) !== (after.contract_version ?? 1)))
    changes.push(`Was ${shownComponent(before, components, running.layout)?.label ?? before.component}`);
  else if (!wasOff) changes.push(...settingChanges(before, after, componentFor(after, components)));
  if ((before.label || "") !== (after.label || ""))
    changes.push(before.label ? `Title was “${before.label}”` : "Has a title");
  const connection = connectionChange(compared, after.id);
  if (connection) changes.push(connection);
  return changes;
}

/** What a member who knows the running design has to look at in this one. `shadow` says
 * whether the running service and the one to start only record their alarms. */
export function compareDesigns(
  running: GraphDocument, design: GraphDocument, components: PipelineComponent[], shadow?: { was: boolean; now: boolean },
): DesignComparison {
  const before = new Map(running.definition.nodes.map((node) => [node.id, node]));
  const shared = new Set(design.definition.nodes.filter((node) => before.has(node.id)).map((node) => node.id));
  const titleOf = (id: string) => { const node = before.get(id); return node ? nodeLabel(node, components, running.layout) : id; };
  const compared: Compared = { running, design, components, shared, titleOf };
  const steps: DesignComparison["steps"] = {};
  for (const node of design.definition.nodes) {
    const was = before.get(node.id);
    if (!was) { steps[node.id] = { kind: "new", detail: "The running design has no such step." }; continue; }
    const changes = stepChanges(compared, was, node);
    if (changes.length) steps[node.id] = { kind: "changed", detail: `${changes.join(". ")}.` };
  }
  const [wasSlots, slots] = [running, design].map((document) => new Set(document.definition.input_slots.map((slot) => slot.id)));
  const added = [...slots!].filter((id) => !wasSlots!.has(id)).length;
  const dropped = [...wasSlots!].filter((id) => !slots!.has(id)).length;
  const [wasSettings, settings] = [running.definition.settings, design.definition.settings];
  return {
    steps,
    removed: running.definition.nodes.filter((node) => !shared.has(node.id)).map((node) => titleOf(node.id)),
    service: [
      ...(shadow && shadow.was !== shadow.now ? [shadow.now ? "Runs in shadow" : "Goes live"] : []),
      ...(added ? [`${plural(added, "input")} added`] : []),
      ...(dropped ? [`${plural(dropped, "input")} removed`] : []),
      ...SETTINGS.filter(([key]) => (wasSettings[key] ?? null) !== (settings[key] ?? null))
        .map(([key, label]) => settingChange(label, wasSettings[key], settings[key])),
    ],
  };
}

/** The comparison in a line, or nothing where the two designs are the same. */
export function comparisonSummary({ steps, removed, service }: DesignComparison): string | undefined {
  const changes = Object.values(steps);
  const fresh = changes.filter((change) => change.kind === "new").length;
  const changed = changes.length - fresh;
  const parts = [
    ...(fresh ? [plural(fresh, "new step")] : []),
    ...(changed ? [plural(changed, "changed step")] : []),
    ...(removed.length ? [`${removed.length} removed (${removed.join(", ")})`] : []),
  ];
  const lines = [...(parts.length ? [parts.join(", ")] : []), ...service];
  return lines.length ? `${lines.join(". ")}.` : undefined;
}
