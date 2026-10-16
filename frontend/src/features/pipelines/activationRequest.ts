import type { PipelineActivationRequest } from "@/types/pipelines.generated";

export function readActivationRequest(
  key: string,
): PipelineActivationRequest | undefined {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return;
    const value: unknown = JSON.parse(raw);
    if (
      value &&
      typeof value === "object" &&
      "idempotency_key" in value &&
      "revision_id" in value &&
      "bindings" in value &&
      "display_name" in value
    )
      return value as PipelineActivationRequest;
  } catch {
    /* The current component also retains uncertain requests in memory. */
  }
}

export function retainActivationRequest(
  key: string,
  request?: PipelineActivationRequest,
): void {
  try {
    if (request) sessionStorage.setItem(key, JSON.stringify(request));
    else sessionStorage.removeItem(key);
  } catch {
    /* Storage can be unavailable; retry within this view still uses the same key. */
  }
}
