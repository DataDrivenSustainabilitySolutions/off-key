import { apiClient, apiUtils } from "@/lib/api-client";
import type {
  Comparison,
  CsvImportQuery,
  DatasetChange,
  DatasetFromHistory,
  DatasetListPage,
  DatasetListQuery,
  DatasetPointsPage,
  DatasetPointsQuery,
  DatasetView,
  LabelChange,
  LabelCreate,
  LabelList,
  LabelSuggestionList,
  LabelSuggestionQuery,
  LabelView,
  RunCreate,
  RunListPage,
  RunListQuery,
  RunMetrics,
  RunPromote,
  RunPromotion,
  RunResultsPage,
  RunResultsQuery,
  RunView,
} from "@/types/dojo.generated";

const base = "/v1/dojo";
const segment = encodeURIComponent;
const dataset = (id: string) => `${base}/datasets/${segment(id)}`;
const run = (id: string) => `${base}/runs/${segment(id)}`;
const read = { redirectOnUnauthorized: false } as const;
// An upload may be 100 MB; the server copies it in one transaction.
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

export const dojoApi = {
  datasets: (query: DatasetListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<DatasetListPage>(`${base}/datasets`, { ...read, signal, params: query }),
  dataset: (id: string, signal?: AbortSignal) => apiUtils.get<DatasetView>(dataset(id), { ...read, signal }),
  importCsv: async (file: Blob, query: CsvImportQuery) => {
    const response = await apiClient.post<DatasetView>(`${base}/datasets/csv`, file, {
      params: query, timeout: UPLOAD_TIMEOUT_MS, headers: { "Content-Type": "text/csv" },
    });
    return response.data;
  },
  importHistory: (request: DatasetFromHistory) =>
    apiUtils.post<DatasetView>(`${base}/datasets/history`, request, { timeout: UPLOAD_TIMEOUT_MS }),
  changeDataset: (id: string, change: DatasetChange) => apiUtils.patch<DatasetView>(dataset(id), change),
  deleteDataset: (id: string) => apiUtils.delete<void>(dataset(id)),
  points: (datasetId: string, seriesId: string, query: DatasetPointsQuery, signal?: AbortSignal) =>
    apiUtils.get<DatasetPointsPage>(`${dataset(datasetId)}/series/${segment(seriesId)}/points`,
      { ...read, signal, params: query }),

  labels: (datasetId: string, signal?: AbortSignal) =>
    apiUtils.get<LabelList>(`${dataset(datasetId)}/labels`, { ...read, signal }),
  labelSuggestions: (datasetId: string, query: LabelSuggestionQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<LabelSuggestionList>(`${dataset(datasetId)}/label-suggestions`, { ...read, signal, params: query }),
  createLabel: (datasetId: string, label: LabelCreate) =>
    apiUtils.post<LabelView>(`${dataset(datasetId)}/labels`, label),
  changeLabel: (datasetId: string, labelId: string, change: LabelChange) =>
    apiUtils.patch<LabelView>(`${dataset(datasetId)}/labels/${segment(labelId)}`, change),
  deleteLabel: (datasetId: string, labelId: string) =>
    apiUtils.delete<void>(`${dataset(datasetId)}/labels/${segment(labelId)}`),

  runs: (query: RunListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<RunListPage>(`${base}/runs`, { ...read, signal, params: query }),
  run: (id: string, signal?: AbortSignal) => apiUtils.get<RunView>(run(id), { ...read, signal }),
  createRun: (request: RunCreate) => apiUtils.post<RunView>(`${base}/runs`, request),
  cancelRun: (id: string) => apiUtils.post<RunView>(`${run(id)}/cancel`),
  deleteRun: (id: string) => apiUtils.delete<void>(run(id)),
  promoteRun: (id: string, request: RunPromote) => apiUtils.post<RunPromotion>(`${run(id)}/promote`, request),
  results: (id: string, query: RunResultsQuery, signal?: AbortSignal) =>
    apiUtils.get<RunResultsPage>(`${run(id)}/results`, { ...read, signal, params: query }),
  metrics: (id: string, signal?: AbortSignal) => apiUtils.get<RunMetrics>(`${run(id)}/metrics`, { ...read, signal }),
  // The server reads `run_ids` once per run, which axios would write as run_ids[].
  compare: (datasetId: string, runIds: string[], signal?: AbortSignal) =>
    apiUtils.get<Comparison>(`${dataset(datasetId)}/comparison?${
      new URLSearchParams(runIds.map(id => ["run_ids", id])).toString()}`, { ...read, signal }),
};
