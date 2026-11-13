import { fieldDefaults } from "@/components/parameter-editor/types";
import type { PipelineCatalog, PipelineComponent, PipelineNode } from "./contracts";
import type { Menu, MenuItem } from "./contextMenu";
import { changeDetector, changeNotice, hasFittedDetector, LEARNING_HELP, learningLabel, type Learning } from "./learning";
import { addBlocker, connectionIssue, detectorIds, freePosition, removeElements, type GraphDocument } from "./model";
import { componentFor, NODE_SIZE, nodePosition, outputKind } from "./semantics";

/** The flow a new service starts from: the one whose detector learns from the stream. */
export const starterTemplate = (catalog: PipelineCatalog) =>
  catalog.templates.find((item) => !hasFittedDetector(item.definition, catalog.components)) ?? catalog.templates[0];

/** The detector the starter flow comes with; it is offered first where a detector is chosen. */
export function suggestedDetector(catalog: PipelineCatalog) {
  const node = starterTemplate(catalog)?.definition.nodes.find((item) => item.kind === "detector");
  return componentFor(node, catalog.components);
}

/** A design with its detectors left out, so that how to detect is the first thing chosen. */
export const withoutDetector = (document: GraphDocument) =>
  removeElements(document, { nodeIds: detectorIds(document.definition) });

/** A card and the room for the wire that leaves it. */
const COLUMN = NODE_SIZE.width + 64;

export type DetectorSlot = {
  /** Where the detector's card goes. */
  position: { x: number; y: number };
  /** The step whose features the detector will read. */
  after?: string;
  /** The calibration step that will read the detector. */
  before?: string;
};

/**
 * Where a design without a detector expects one: after the last step that hands on
 * features, before the calibration step. Undefined once the design has a detector.
 */
export function detectorSlot(document: GraphDocument, components: PipelineComponent[]): DetectorSlot | undefined {
  const { definition, layout } = document;
  if (definition.nodes.some((node) => node.kind === "detector")) return;
  const boxes = new Map(definition.nodes.map((node, index) => [node.id, nodePosition(layout, node.id, index)]));
  const loose = definition.nodes.filter((node) =>
    outputKind(node, componentFor(node, components)) === "features"
    && !definition.edges.some((edge) => edge.source === node.id));
  // The flow continues from a step the readings reach; a step that reads nothing yet is
  // no place to continue from. Of several loose ends, the one furthest along the flow.
  const fed = new Set(definition.nodes.filter((node) => node.kind === "source").map((node) => node.id));
  for (let grown = true; grown; ) {
    grown = false;
    for (const edge of definition.edges)
      if (fed.has(edge.source) && !fed.has(edge.target)) {
        fed.add(edge.target);
        grown = true;
      }
  }
  const ends = loose.filter((node) => fed.has(node.id));
  const after = (ends.length ? ends : loose)
    .sort((left, right) => boxes.get(right.id)!.x - boxes.get(left.id)!.x)[0]?.id;
  const calibration = definition.nodes.find((node) => node.kind === "calibration");
  const before = calibration && !definition.edges.some((edge) => edge.target === calibration.id)
    ? calibration.id : undefined;
  if (before) {
    const next = boxes.get(before)!;
    const spot = { x: next.x - COLUMN, y: next.y };
    const free = ![...boxes.values()].some((box) =>
      Math.abs(box.x - spot.x) < NODE_SIZE.width + 32 && Math.abs(box.y - spot.y) < NODE_SIZE.height + 16);
    if (free && (!after || boxes.get(after)!.x + COLUMN <= spot.x)) return { position: spot, after, before };
  }
  return { position: freePosition(document, after), after, before };
}

/**
 * Put a detector into the slot: placed there, reading the step before it and read by the
 * calibration step. As when a detector's model is changed, the learned steps before it and
 * the detection rule follow how it learns; `notice` says so when they did.
 */
export function fillDetectorSlot(
  document: GraphDocument,
  component: PipelineComponent,
  components: PipelineComponent[],
): { document: GraphDocument; id: string; notice: string } | undefined {
  const slot = detectorSlot(document, components);
  if (!slot || component.kind !== "detector" || addBlocker(document.definition, component)) return;
  const { definition, layout } = document;
  let id = "detector";
  for (let suffix = 2; definition.nodes.some((node) => node.id === id); suffix++) id = `detector_${suffix}`;
  const node: PipelineNode = {
    id, kind: "detector", component: component.id,
    contract_version: component.contract_version ?? 1, params: fieldDefaults(component.fields),
  };
  // Steps are listed in the order the flow reads: the detector comes before its calibration.
  const index = definition.nodes.findIndex((item) => item.kind === "calibration");
  const nodes = index < 0 ? [...definition.nodes, node]
    : [...definition.nodes.slice(0, index), node, ...definition.nodes.slice(index)];
  const placed = { ...definition, nodes };
  const links = [[slot.after, id], [id, slot.before]]
    .filter((link): link is [string, string] => !!link[0] && !!link[1]
      && !connectionIssue(placed, link[0], link[1], components))
    .map(([source, target]) => ({ source, target, order: 0 }));
  const change = changeDetector({ ...placed, edges: [...links, ...definition.edges] }, id, component, components);
  return {
    id,
    notice: changeNotice(change, component.learning),
    document: {
      definition: change.definition,
      layout: { ...layout, nodes: { ...layout.nodes, [id]: slot.position } },
    },
  };
}

const GROUPS: Learning[] = ["online", "batch", "pretrained", "none"];

/** The detectors to choose from: the suggested one first, then all of them by how they
 * learn. Typing lists the matching detectors directly. The list names them; what the one
 * in focus does is read in full below it. */
export function detectorMenu(
  components: PipelineComponent[],
  suggested: PipelineComponent | undefined,
  pick: (component: PipelineComponent) => void,
): Menu {
  const detectors = components.filter((component) => component.kind === "detector")
    .sort((left, right) => left.label.localeCompare(right.label));
  const entry = (component: PipelineComponent, detail?: string): MenuItem => ({
    key: component.id, label: component.label, detail, help: component.description, blocked: component.unavailable,
    run: () => pick(component),
  });
  const groups = GROUPS.map((mode) => ({
    mode,
    label: learningLabel({ learning: mode, kind: "detector" }) ?? "Other",
    items: detectors.filter((component) => (component.learning ?? "none") === mode),
  })).filter((group) => group.items.length);
  const offered = suggested && detectors.includes(suggested) && !suggested.unavailable ? suggested : undefined;
  return {
    label: "Choose a detector",
    empty: "No detector is available.",
    items: [
      ...(offered ? [{ ...entry(offered, "Suggested"), key: `suggested:${offered.id}` }] : []),
      ...groups.map((group, position): MenuItem => ({
        key: group.mode, label: group.label, detail: `${group.items.length}`, help: LEARNING_HELP[group.mode],
        separated: position === 0 && !!offered,
        submenu: { label: group.label, items: group.items.map((component) => entry(component)) },
      })),
    ],
    search: {
      label: "Search detectors",
      results: (query) => {
        const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
        return detectors
          .filter((component) => {
            const text = `${component.label} ${component.description} ${component.library ?? ""} ${learningLabel(component) ?? ""}`
              .toLocaleLowerCase();
            return words.every((word) => text.includes(word));
          })
          .map((component) => entry(component, [component.library, learningLabel(component)].filter(Boolean).join(" · ")));
      },
    },
  };
}
