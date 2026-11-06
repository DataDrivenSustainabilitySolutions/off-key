import { apiUtils, type ApiRequestOptions } from "@/lib/api-client";
import type { RuleChange } from "@/types/system";
import type { SystemCollectionPreview, SystemConnectionCheck, SystemDocument, SystemSnapshot } from "@/types/system";

const CATALOGUE_ENDPOINT = "/v1/catalogue";
const RECORDING_ENDPOINT = "/v1/recording";

type CollectionStatus = { revision: number; runtime: SystemSnapshot["runtime"] };

/** Every catalogue request; callers pass their own abort and redirect options. */
export const systemApi = {
  get: (options?: ApiRequestOptions) =>
    apiUtils.get<SystemSnapshot>(CATALOGUE_ENDPOINT, options),
  save: (expectedRevision: number, document: SystemDocument, options?: ApiRequestOptions) =>
    apiUtils.put<SystemSnapshot>(CATALOGUE_ENDPOINT, { expected_revision: expectedRevision, document }, options),
  applyCollection: (change: RuleChange, options?: ApiRequestOptions) =>
    apiUtils.put<SystemSnapshot>(RECORDING_ENDPOINT, change, options),
  collectionStatus: (streamIds: string[], options?: ApiRequestOptions) =>
    apiUtils.post<CollectionStatus>(`${RECORDING_ENDPOINT}/status`, { reading_ids: streamIds }, options),
  previewCollection: (change: RuleChange, options?: ApiRequestOptions) =>
    apiUtils.post<SystemCollectionPreview>(`${RECORDING_ENDPOINT}/preview`, change, options),
  checkConnection: (connectionId: string, options?: ApiRequestOptions) =>
    apiUtils.post<SystemConnectionCheck>("/v1/brokers/check", { broker_id: connectionId }, options),
  /** Retry a recorded broker now instead of waiting for its automatic retry. */
  reconnectConnection: (connectionId: string, options?: ApiRequestOptions) =>
    apiUtils.post<{ broker_id: string }>(`/v1/brokers/${encodeURIComponent(connectionId)}/reconnect`, undefined, options),
};
