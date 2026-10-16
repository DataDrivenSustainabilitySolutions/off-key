import type * as Wire from "@/types/pipelines.generated";
import type { JsonValue } from "@/types/monitoring";
import type { FieldDescriptor } from "./ParameterFields";

export type PipelineNode = Omit<Wire.PipelineNode, "params"> & {
  params: Record<string, JsonValue>;
};
export type PipelineEdge = Required<Wire.PipelineEdge>;
export type PipelineDefinition = Omit<
  Wire.PipelineDefinition,
  "nodes" | "edges" | "settings" | "input_slots" | "strategy"
> & {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  settings: Required<Wire.PipelineSettings>;
  input_slots: Wire.InputSlot[];
  strategy: "static_baseline" | "adaptive_stream";
};
export type PipelineLayout = Wire.PipelineLayout & {
  nodes: NonNullable<Wire.PipelineLayout["nodes"]>;
};
export type PipelineComponent = Omit<Wire.PipelineComponent, "fields"> & {
  fields: FieldDescriptor[];
};
export type PipelineRevisionView = Omit<
  Wire.PipelineRevisionView,
  "definition"
> & { definition: PipelineDefinition };
export type PipelineView = Omit<
  Wire.PipelineView,
  "draft" | "layout" | "revisions"
> & {
  draft: PipelineDefinition;
  layout: PipelineLayout;
  revisions: PipelineRevisionView[];
};
export type PipelineValidation = Omit<
  Wire.PipelineValidation,
  "definition" | "features" | "issues"
> & {
  definition: PipelineDefinition;
  features: NonNullable<Wire.PipelineValidation["features"]>;
  issues: NonNullable<Wire.PipelineValidation["issues"]>;
};
export type PipelineCatalog = Omit<
  Wire.PipelineCatalog,
  "components" | "templates"
> & {
  components: PipelineComponent[];
  templates: Array<
    Omit<Wire.PipelineTemplate, "definition" | "layout"> & {
      definition: PipelineDefinition;
      layout: PipelineLayout;
    }
  >;
};
export type PipelineServiceView = Omit<
  Wire.PipelineServiceView,
  "definition" | "layout" | "validation"
> & {
  definition: PipelineDefinition;
  layout: PipelineLayout;
  validation?: PipelineValidation | null;
};

export function normalizeDefinition(
  definition: Wire.PipelineDefinition,
): PipelineDefinition {
  return {
    ...definition,
    strategy: definition.strategy ?? "static_baseline",
    input_slots: definition.input_slots ?? [],
    nodes: (definition.nodes ?? []).map((node) => ({
      ...node,
      params: (node.params ?? {}) as Record<string, JsonValue>,
    })),
    edges: (definition.edges ?? []).map((edge) => ({
      ...edge,
      order: edge.order ?? 0,
    })),
    settings: {
      training_window_size: 1200,
      calibration_window_size: 360,
      seed: 42,
      conformal_strategy: "split",
      ...definition.settings,
    },
  };
}
export function normalizeLayout(layout?: Wire.PipelineLayout): PipelineLayout {
  return { ...layout, nodes: layout?.nodes ?? {} };
}
export function normalizeRevision(
  revision: Wire.PipelineRevisionView,
): PipelineRevisionView {
  return { ...revision, definition: normalizeDefinition(revision.definition) };
}
export function normalizeView(view: Wire.PipelineView): PipelineView {
  return {
    ...view,
    draft: normalizeDefinition(view.draft),
    layout: normalizeLayout(view.layout),
    revisions: (view.revisions ?? []).map(normalizeRevision),
  };
}
export function normalizeCatalog(
  catalog: Wire.PipelineCatalog,
): PipelineCatalog {
  return {
    ...catalog,
    components: catalog.components.map((component) => ({
      ...component,
      fields: (component.fields ?? []) as FieldDescriptor[],
    })),
    templates: catalog.templates.map((template) => ({
      ...template,
      definition: normalizeDefinition(template.definition),
      layout: normalizeLayout(template.layout),
    })),
  };
}
export function normalizeValidation(
  validation: Wire.PipelineValidation,
): PipelineValidation {
  return {
    ...validation,
    definition: normalizeDefinition(validation.definition),
    features: validation.features ?? {},
    issues: validation.issues ?? [],
  };
}
export function normalizeService(
  view: Wire.PipelineServiceView,
): PipelineServiceView {
  return {
    ...view,
    definition: normalizeDefinition(view.definition),
    layout: normalizeLayout(view.layout),
    validation: view.validation ? normalizeValidation(view.validation) : null,
  };
}
