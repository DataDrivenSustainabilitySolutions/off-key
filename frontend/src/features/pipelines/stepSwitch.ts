import type { PipelineComponent } from "./contracts";
import type { GraphDocument } from "./model";
import { PASS_THROUGH, switchedOff } from "./semantics";

/**
 * Why a step cannot be switched off; undefined when it can. Only a step that takes features and
 * gives features can stand aside, because what follows it then takes what came before it.
 */
export function switchOffBlocker(document: GraphDocument, id: string, components: PipelineComponent[]): string | undefined {
  const node = document.definition.nodes.find((item) => item.id === id);
  if (!node) return "This step is gone.";
  if (switchedOff(document.layout, node)) return "This step is switched off already.";
  if (node.kind !== "transform" || node.component === PASS_THROUGH) return "Only a step that changes features can be switched off.";
  const stand = components.find((component) => component.id === PASS_THROUGH);
  if (!stand || stand.unavailable) return "This deployment cannot pass features through a step.";
  return undefined;
}

/**
 * Switch steps off: each becomes a pass-through step, so the design runs without it and reads
 * exactly as it runs, and the layout keeps what the step was. Steps that cannot be switched
 * off stay as they are.
 */
export function switchOff(document: GraphDocument, ids: Iterable<string>, components: PipelineComponent[]): GraphDocument {
  const chosen = new Set([...ids].filter((id) => !switchOffBlocker(document, id, components)));
  if (!chosen.size) return document;
  const stand = components.find((component) => component.id === PASS_THROUGH)!;
  const remembered = { ...document.layout.switched_off };
  const nodes = document.definition.nodes.map((node) => {
    if (!chosen.has(node.id)) return node;
    remembered[node.id] = { component: node.component, params: node.params,
      ...(node.contract_version === undefined ? {} : { contract_version: node.contract_version }) };
    return { ...node, component: PASS_THROUGH, contract_version: stand.contract_version ?? 1, params: {} };
  });
  return { definition: { ...document.definition, nodes }, layout: { ...document.layout, switched_off: remembered } };
}

/** Switch steps on again, with the settings they had. */
export function switchOn(document: GraphDocument, ids: Iterable<string>): GraphDocument {
  const chosen = new Set(ids);
  const remembered = { ...document.layout.switched_off };
  let changed = false;
  const nodes = document.definition.nodes.map((node) => {
    const was = chosen.has(node.id) ? switchedOff(document.layout, node) : undefined;
    if (!was) return node;
    changed = true;
    delete remembered[node.id];
    // Exactly as it was, so that switching a step off and on again leaves the design unchanged.
    const back = { ...node, component: was.component, params: was.params as typeof node.params,
      contract_version: was.contract_version as typeof node.contract_version };
    if (was.contract_version === undefined) delete back.contract_version;
    return back;
  });
  return changed ? { definition: { ...document.definition, nodes }, layout: { ...document.layout, switched_off: remembered } } : document;
}

/** What Switch off or Switch on does to the chosen steps: those that are on go off; when none can, those that are off come on. */
export function switchSteps(document: GraphDocument, ids: string[], components: PipelineComponent[]) {
  const on = ids.filter((id) => !switchOffBlocker(document, id, components));
  const off = ids.filter((id) => switchedOff(document.layout, document.definition.nodes.find((node) => node.id === id)));
  if (on.length) return { document: switchOff(document, on, components), ids: on, off: true };
  if (off.length) return { document: switchOn(document, off), ids: off, off: false };
  return undefined;
}
