import { apiUtils, type ApiRequestOptions } from "@/lib/api-client";
import type { RuleChange } from "./systemTypes";
import type { SystemCollectionPreview, SystemDocument, SystemSnapshot } from "./systemTypes";

export const SYSTEM_ENDPOINT = "/v1/system";

type CollectionStatus = { revision: number; runtime: SystemSnapshot["runtime"] };

/** Every catalogue request; callers pass their own abort and redirect options. */
export const systemApi = {
  get: (options?: ApiRequestOptions) =>
    apiUtils.get<SystemSnapshot>(SYSTEM_ENDPOINT, options),
  save: (expectedRevision: number, document: SystemDocument, options?: ApiRequestOptions) =>
    apiUtils.put<SystemSnapshot>(SYSTEM_ENDPOINT, { expected_revision: expectedRevision, document }, options),
  applyCollection: (change: RuleChange, options?: ApiRequestOptions) =>
    apiUtils.put<SystemSnapshot>(`${SYSTEM_ENDPOINT}/collection`, change, options),
  collectionStatus: (streamIds: string[], options?: ApiRequestOptions) =>
    apiUtils.post<CollectionStatus>(`${SYSTEM_ENDPOINT}/collection/status`, { stream_ids: streamIds }, options),
  previewCollection: (change: RuleChange, options?: ApiRequestOptions) =>
    apiUtils.post<SystemCollectionPreview>(`${SYSTEM_ENDPOINT}/collection/preview`, change, options),
};
