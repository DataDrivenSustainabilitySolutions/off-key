import { apiClient, apiUtils } from "@/lib/api-client";
import type {
  BenchmarkImport, BenchmarkImportResult, BenchmarkListPage, BenchmarkListQuery, Comparison, CsvImportQuery, DatasetChange, DatasetFromHistory, DatasetListPage, DatasetListQuery, DatasetPointsPage, DatasetPointsQuery, DatasetView, DojoDeletion, DojoDeletionResult, FaultSuiteCreate, LabelBatch, LabelChange, LabelCreate, LabelList, LabelRule, LabelSuggestionList, LabelSuggestionQuery, LabelView, MethodComparison, PendingLabelAccept, PendingLabelDismiss, PendingLabelList, PendingLabelsMade, RunCreate, RunListPage, RunListQuery, RunMetrics, RunOutline, RunOutlineQuery, RunPromote, RunPromotion, RunResultsPage, RunResultsQuery, RunSteps, RunView, StudyComparison, StudyComparisonQuery, StudyCreate, StudyListPage, StudyListQuery, StudyView, SuiteCreate, SuiteListPage, SuiteListQuery, SuiteView,
} from "@/types/dojo.generated";

const base = "/v1/dojo";
const segment = encodeURIComponent;
const dataset = (id: string) => `${base}/datasets/${segment(id)}`;
const run = (id: string) => `${base}/runs/${segment(id)}`;
const suite = (id: string) => `${base}/suites/${segment(id)}`;
const study = (id: string) => `${base}/studies/${segment(id)}`;
// An upload may be 100 MB; the server copies it in one transaction.
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

export const dojoApi = {
  datasets: (query: DatasetListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<DatasetListPage>(`${base}/datasets`, { signal, params: query }),
  dataset: (id: string, signal?: AbortSignal) => apiUtils.get<DatasetView>(dataset(id), { signal }),
  importCsv: async (file: Blob, query: CsvImportQuery) => {
    const response = await apiClient.post<DatasetView>(`${base}/datasets/csv`, file, {
      params: query, timeout: UPLOAD_TIMEOUT_MS, headers: { "Content-Type": "text/csv" },
    });
    return response.data;
  },
  benchmarks: (query: BenchmarkListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<BenchmarkListPage>(`${base}/benchmarks`, { signal, params: query }),
  // The server downloads every series from the collection's mirror before it answers.
  importBenchmarks: (request: BenchmarkImport) =>
    apiUtils.post<BenchmarkImportResult>(`${base}/benchmarks/import`, request, { timeout: UPLOAD_TIMEOUT_MS }),
  importHistory: (request: DatasetFromHistory) =>
    apiUtils.post<DatasetView>(`${base}/datasets/history`, request, { timeout: UPLOAD_TIMEOUT_MS }),
  changeDataset: (id: string, change: DatasetChange) => apiUtils.patch<DatasetView>(dataset(id), change),
  deleteDataset: (id: string) => apiUtils.delete<void>(dataset(id)),
  points: (datasetId: string, seriesId: string, query: DatasetPointsQuery, signal?: AbortSignal) =>
    apiUtils.get<DatasetPointsPage>(`${dataset(datasetId)}/series/${segment(seriesId)}/points`,
      { signal, params: query }),

  labels: (datasetId: string, signal?: AbortSignal) =>
    apiUtils.get<LabelList>(`${dataset(datasetId)}/labels`, { signal }),
  labelSuggestions: (datasetId: string, query: LabelSuggestionQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<LabelSuggestionList>(`${dataset(datasetId)}/label-suggestions`, { signal, params: query }),
  createLabel: (datasetId: string, label: LabelCreate) =>
    apiUtils.post<LabelView>(`${dataset(datasetId)}/labels`, label),
  // One write for many labels, so adding every suggestion stays within the write rate limit.
  createLabels: (datasetId: string, batch: LabelBatch) =>
    apiUtils.post<LabelList>(`${dataset(datasetId)}/labels/batch`, batch),
  changeLabel: (datasetId: string, labelId: string, change: LabelChange) =>
    apiUtils.patch<LabelView>(`${dataset(datasetId)}/labels/${segment(labelId)}`, change),
  deleteLabel: (datasetId: string, labelId: string) =>
    apiUtils.delete<void>(`${dataset(datasetId)}/labels/${segment(labelId)}`),
  // Proposed labels wait for a member to add or dismiss them; they score no run until then.
  pendingLabels: (datasetId: string, signal?: AbortSignal) =>
    apiUtils.get<PendingLabelList>(`${dataset(datasetId)}/pending-labels`, { signal }),
  proposeLabelsByRule: (datasetId: string, rule: LabelRule) =>
    apiUtils.post<PendingLabelsMade>(`${dataset(datasetId)}/pending-labels/by-rule`, rule),
  acceptPendingLabels: (datasetId: string, choice: PendingLabelAccept) =>
    apiUtils.post<LabelList>(`${dataset(datasetId)}/pending-labels/accept`, choice),
  dismissPendingLabels: (datasetId: string, dismissal: PendingLabelDismiss) =>
    apiUtils.post<void>(`${dataset(datasetId)}/pending-labels/dismiss`, dismissal),

  runs: (query: RunListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<RunListPage>(`${base}/runs`, { signal, params: query }),
  run: (id: string, signal?: AbortSignal) => apiUtils.get<RunView>(run(id), { signal }),
  createRun: (request: RunCreate) => apiUtils.post<RunView>(`${base}/runs`, request),
  cancelRun: (id: string) => apiUtils.post<RunView>(`${run(id)}/cancel`),
  deleteRun: (id: string) => apiUtils.delete<void>(run(id)),
  promoteRun: (id: string, request: RunPromote) => apiUtils.post<RunPromotion>(`${run(id)}/promote`, request),
  results: (id: string, query: RunResultsQuery, signal?: AbortSignal) =>
    apiUtils.get<RunResultsPage>(`${run(id)}/results`, { signal, params: query }),
  // Scores, boundary and alarms per stretch of time: enough to draw a run without reading every result.
  outline: (id: string, query: RunOutlineQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<RunOutline>(`${run(id)}/outline`, { signal, params: query }),
  // What a few observations of an ended run looked like at every step of its design.
  steps: (id: string) => apiUtils.get<RunSteps>(`${run(id)}/steps`),
  metrics: (id: string, signal?: AbortSignal) => apiUtils.get<RunMetrics>(`${run(id)}/metrics`, { signal }),
  calibration: (id: string, signal?: AbortSignal) =>
    apiUtils.get<MethodComparison>(`${run(id)}/calibration`, { signal }),
  // The server reads `run_ids` once per run, which axios would write as run_ids[].
  compare: (datasetId: string, runIds: string[], signal?: AbortSignal) =>
    apiUtils.get<Comparison>(`${dataset(datasetId)}/comparison?${
      new URLSearchParams(runIds.map(id => ["run_ids", id])).toString()}`, { signal }),

  // A suite is a fixed list of datasets; a study runs one design over all of them.
  suites: (query: SuiteListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<SuiteListPage>(`${base}/suites`, { signal, params: query }),
  suite: (id: string, signal?: AbortSignal) => apiUtils.get<SuiteView>(suite(id), { signal }),
  createSuite: (request: SuiteCreate) => apiUtils.post<SuiteView>(`${base}/suites`, request),
  // Copies every value once per copy, so it may take a while on a long history.
  createFaultSuite: (request: FaultSuiteCreate) =>
    apiUtils.post<SuiteView>(`${base}/suites/faults`, request, { timeout: UPLOAD_TIMEOUT_MS }),
  deleteSuite: (id: string) => apiUtils.delete<void>(suite(id)),
  /** Several suites, studies and datasets in one write: suites first, so a dataset freed by its suite goes too. */
  deleteItems: (request: DojoDeletion) => apiUtils.post<DojoDeletionResult>(`${base}/deletions`, request),
  reviewSuite: (id: string) => apiUtils.post<SuiteView>(`${suite(id)}/review`),
  compareStudies: (suiteId: string, query: StudyComparisonQuery, signal?: AbortSignal) =>
    apiUtils.get<StudyComparison>(`${suite(suiteId)}/comparison`, { signal, params: query }),
  studies: (query: StudyListQuery = {}, signal?: AbortSignal) =>
    apiUtils.get<StudyListPage>(`${base}/studies`, { signal, params: query }),
  // Reading a study calculates the metrics its finished runs still lack, for a few seconds.
  study: (id: string, signal?: AbortSignal) => apiUtils.get<StudyView>(study(id), { signal }),
  createStudy: (request: StudyCreate) => apiUtils.post<StudyView>(`${base}/studies`, request),
  cancelStudy: (id: string) => apiUtils.post<StudyView>(`${study(id)}/cancel`),
  deleteStudy: (id: string) => apiUtils.delete<void>(study(id)),
};
