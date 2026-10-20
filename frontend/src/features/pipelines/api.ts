import { apiUtils } from "@/lib/api-client";
import type {
  PipelineActivationRequest,
  PipelineActivationView,
  PipelineApplyRequest,
  PipelineCatalog,
  PipelineCreate,
  PipelineDefinition,
  PipelineDraftSave,
  PipelineHistoryPage,
  PipelineLayout,
  PipelineListPage,
  PipelineListQuery,
  PipelineMetadataChange,
  PipelinePublish,
  PipelineRevisionPage,
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

const base = "/v1/monitors/pipelines";
const item = (id: string) => `${base}/${encodeURIComponent(id)}`;
const monitor = (id: string) => `/v1/monitors/${encodeURIComponent(id)}`;
export const pipelinesApi = {
  apply: (request: PipelineApplyRequest) =>
    apiUtils.post<PipelineActivationView>(`${base}/apply`, request),
  catalog: (signal?: AbortSignal) =>
    apiUtils
      .get<PipelineCatalog>(`${base}/catalog`, {
        signal,
        redirectOnUnauthorized: false,
      })
      .then(normalizeCatalog),
  list: (query: PipelineListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<PipelineListPage>(base, {
      signal,
      redirectOnUnauthorized: false,
      params: query,
    }),
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
    id: string | undefined,
    definition: PipelineDefinition,
    signal?: AbortSignal,
    selectedNodeId?: string,
  ) =>
    apiUtils
      .post<PipelineValidationReport>(
        id ? `${item(id)}/validate` : `${base}/validate`,
        { definition, selected_node_id: selectedNodeId },
        { signal },
      )
      .then((report) => normalizeValidation(report, definition)),
  publish: (id: string, request: PipelinePublish) =>
    apiUtils
      .post<PipelineRevisionView>(`${item(id)}/revisions`, request)
      .then(normalizeRevision),
  revisions: (id: string, before?: number, signal?: AbortSignal) =>
    apiUtils.get<PipelineRevisionPage>(`${item(id)}/revisions`, {
      signal,
      params: { before },
      redirectOnUnauthorized: false,
    }),
  revision: (id: string, revisionId: string, signal?: AbortSignal) =>
    apiUtils
      .get<PipelineRevisionView>(
        `${item(id)}/revisions/${encodeURIComponent(revisionId)}`,
        { signal, redirectOnUnauthorized: false },
      )
      .then(normalizeRevision),
  revisionMetadata: (
    id: string,
    revisionId: string,
    definition: PipelineDefinition,
    selectedNodeId: string,
    signal?: AbortSignal,
  ) =>
    apiUtils
      .get<PipelineValidationReport>(
        `${item(id)}/revisions/${encodeURIComponent(revisionId)}/metadata`,
        {
          signal,
          params: { selected_node_id: selectedNodeId },
          redirectOnUnauthorized: false,
        },
      )
      .then((report) => normalizeValidation(report, definition)),
  service: (id: string, signal?: AbortSignal, selectedNodeId?: string) =>
    apiUtils
      .get<PipelineServiceView>(
        `${monitor(id)}/pipeline`,
        {
          signal,
          redirectOnUnauthorized: false,
          params: selectedNodeId
            ? { selected_node_id: selectedNodeId }
            : undefined,
        },
      )
      .then(normalizeService),
  history: (serviceId: string, signal?: AbortSignal) =>
    apiUtils.get<PipelineHistoryPage>(`${monitor(serviceId)}/pipeline-history`, {
      signal,
      redirectOnUnauthorized: false,
    }),
  runMetadata: (
    serviceId: string,
    definition: PipelineDefinition,
    selectedNodeId: string,
    signal?: AbortSignal,
  ) =>
    apiUtils
      .get<PipelineValidationReport>(`${monitor(serviceId)}/pipeline-metadata`, {
        signal,
        params: { selected_node_id: selectedNodeId },
        redirectOnUnauthorized: false,
      })
      .then((report) => normalizeValidation(report, definition)),
  saveLayout: (id: string, layout: PipelineLayout) =>
    apiUtils
      .put<PipelineLayout>(
        `${monitor(id)}/pipeline-layout`,
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
