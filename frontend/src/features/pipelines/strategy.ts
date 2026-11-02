import { fieldDefaults } from "@/components/parameter-editor/types";
import type { PipelineCatalog, PipelineComponent, PipelineDefinition, PipelineNode } from "./contracts";
import type { GraphDocument } from "./model";
import { componentFor } from "./semantics";

export type Strategy = PipelineDefinition["strategy"];

/** Learned steps and models that do the same job under the other strategy. Detectors
 * without an equivalent, and the policy, become the other strategy's template choice. */
const COUNTERPARTS: [static_: string, adaptive: string][] = [
  ["static.standard_scaler", "adaptive.standard_scaler"],
  ["static.min_max_scaler", "adaptive.min_max_scaler"],
  ["static.robust_scaler", "adaptive.robust_scaler"],
  ["static.pca", "adaptive.uncentered_pca"],
  ["static.random_projection", "adaptive.random_projection"],
  ["detector:pyod_iforest", "detector:aberrant_online_isolation_forest"],
  ["detector:pyod_knn", "detector:aberrant_knn"],
  ["detector:pyod_lof", "detector:aberrant_local_outlier_factor"],
  ["detector:pyod_ocsvm", "detector:aberrant_incremental_one_class_svm_adaptive_kernel"],
];

function counterpart(node: PipelineNode, strategy: Strategy, catalog: PipelineCatalog) {
  const pair = COUNTERPARTS.find((item) => item.includes(node.component));
  const paired = pair && catalog.components.find((component) =>
    component.id === pair[strategy === "static_baseline" ? 0 : 1] && component.kind === node.kind);
  if (paired?.strategies.includes(strategy)) return paired;
  if (node.kind !== "detector" && node.kind !== "policy") return undefined;
  const template = catalog.templates.find((item) => item.definition.strategy === strategy);
  const chosen = template?.definition.nodes.find((item) => item.kind === node.kind)?.component;
  return catalog.components.find((component) => component.id === chosen && component.strategies.includes(strategy));
}

/** A learned step keeps the settings both versions share; a model starts from its defaults.
 * The policy keeps how it combines detectors, which both policies share. */
function convertedParams(node: PipelineNode, component: PipelineComponent) {
  const params = fieldDefaults(component.fields);
  if (node.kind === "policy" && node.params.fusion !== undefined
    && component.fields.some((field) => field.name === "fusion"))
    params.fusion = structuredClone(node.params.fusion);
  if (node.kind !== "transform") return params;
  for (const field of component.fields)
    if (field.name in node.params) params[field.name] = structuredClone(node.params[field.name]!);
  return params;
}

export type StrategyChange = {
  document: GraphDocument;
  /** Steps whose component changed, by node id. */
  converted: string[];
  /** Steps without a counterpart; validation names what to do with them. */
  unconverted: string[];
};

/** Switch the strategy and move every step that only exists under the old one to its
 * counterpart. Node ids, titles, connections and the learning windows stay. */
export function convertStrategy(document: GraphDocument, strategy: Strategy, catalog: PipelineCatalog): StrategyChange {
  const converted: string[] = [];
  const unconverted: string[] = [];
  const nodes = document.definition.nodes.map((node) => {
    const component = componentFor(node, catalog.components);
    if (component?.strategies.includes(strategy)) return node;
    const replacement = counterpart(node, strategy, catalog);
    if (!replacement) {
      unconverted.push(node.id);
      return node;
    }
    converted.push(node.id);
    return {
      ...node,
      component: replacement.id,
      contract_version: replacement.contract_version ?? 1,
      params: convertedParams(node, replacement),
    };
  });
  return {
    document: { ...document, definition: { ...document.definition, strategy, nodes } },
    converted,
    unconverted,
  };
}
