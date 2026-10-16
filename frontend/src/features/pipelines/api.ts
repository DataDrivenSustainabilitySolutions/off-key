import { apiUtils } from "@/lib/api-client";
import type {
  PipelineActivationRequest,
  PipelineActivationView,
  PipelineCatalog,
  PipelineCreate,
  PipelineDefinition,
  PipelineDraftSave,
  PipelineMetadataChange,
  PipelinePublish,
  PipelineRevisionView,
  PipelineServiceView,
  PipelineValidationReport,
  PipelineView,
} from "@/types/pipelines.generated";
import {
  normalizeCatalog,
  normalizeLayout,
  normalizeRevision,
  normalizeService,
  normalizeValidation,
  normalizeView,
} from "./contracts";
import type { PipelineLayout } from "@/types/pipelines.generated";

const base = "/v1/monitors/pipelines";
const item = (id: string) => `${base}/${encodeURIComponent(id)}`;
export const pipelinesApi = {
  catalog: (signal?: AbortSignal) =>
    apiUtils
      .get<PipelineCatalog>(`${base}/catalog`, {
        signal,
        redirectOnUnauthorized: false,
      })
      .then(normalizeCatalog),
  list: (signal?: AbortSignal) =>
    apiUtils
      .get<PipelineView[]>(base, { signal, redirectOnUnauthorized: false })
      .then((items) => items.map(normalizeView)),
  get: (id: string, signal?: AbortSignal) =>
    apiUtils
      .get<PipelineView>(item(id), { signal, redirectOnUnauthorized: false })
      .then(normalizeView),
  create: (request: PipelineCreate) =>
    apiUtils.post<PipelineView>(base, request).then(normalizeView),
  save: (id: string, request: PipelineDraftSave) =>
    apiUtils
      .put<PipelineView>(`${item(id)}/draft`, request)
      .then(normalizeView),
  metadata: (id: string, request: PipelineMetadataChange) =>
    apiUtils.patch<PipelineView>(item(id), request).then(normalizeView),
  validate: (
    id: string,
    definition: PipelineDefinition,
    signal?: AbortSignal,
    selectedNodeId?: string,
  ) =>
    apiUtils
      .post<PipelineValidationReport>(
        `${item(id)}/validate`,
        { definition, selected_node_id: selectedNodeId },
        { signal },
      )
      .then((report) => normalizeValidation(report, definition)),
  publish: (id: string, request: PipelinePublish) =>
    apiUtils
      .post<PipelineRevisionView>(`${item(id)}/revisions`, request)
      .then(normalizeRevision),
  service: (id: string, signal?: AbortSignal, selectedNodeId?: string) =>
    apiUtils
      .get<PipelineServiceView>(
        `/v1/monitors/${encodeURIComponent(id)}/pipeline`,
        {
          signal,
          redirectOnUnauthorized: false,
          params: selectedNodeId
            ? { selected_node_id: selectedNodeId }
            : undefined,
        },
      )
      .then(normalizeService),
  saveLayout: (id: string, layout: PipelineLayout) =>
    apiUtils
      .put<PipelineLayout>(
        `/v1/monitors/${encodeURIComponent(id)}/pipeline-layout`,
        layout,
      )
      .then(normalizeLayout),
  activate: (request: PipelineActivationRequest) =>
    apiUtils.post<PipelineActivationView>(
      "/v1/monitors/pipeline-activations",
      request,
    ),
  activation: (id: string, signal?: AbortSignal) =>
    apiUtils.get<PipelineActivationView>(
      `/v1/monitors/pipeline-activations/${encodeURIComponent(id)}`,
      { signal, redirectOnUnauthorized: false },
    ),
  cancel: (id: string) =>
    apiUtils.delete<PipelineActivationView>(
      `/v1/monitors/pipeline-activations/${encodeURIComponent(id)}`,
    ),
};
