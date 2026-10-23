import { useCallback, useEffect, useSyncExternalStore } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { createDraftStore, navigationDraft } from "@/lib/navigation-draft";
import type { PipelineActivationView, PipelineApplyRequest } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";

export const applyFinished = (operation?: PipelineActivationView) =>
  !!operation && ["succeeded", "failed", "cancelled"].includes(operation.phase);

type Snapshot = {
  request?: PipelineApplyRequest;
  operation?: PipelineActivationView;
  busy: boolean;
  error: string;
};

/** An immutable request outlives navigation and uncertain network responses. */
export function createApplySession(storageKey: string) {
  const { getSnapshot, subscribe, update } = createDraftStore<Snapshot>(storageKey, (value) => {
    const stored = value as Partial<Snapshot> | undefined;
    return { request: stored?.request, operation: stored?.operation, busy: false, error: "" };
  }, (next) => ({ request: next.request, operation: next.operation }));
  return {
    getSnapshot,
    subscribe,
    submit: async (request?: PipelineApplyRequest) => {
      if (getSnapshot().busy || getSnapshot().operation) return;
      const immutable = getSnapshot().request ?? request;
      if (!immutable) return;
      update({ request: immutable, busy: true, error: "" });
      try {
        const operation = await pipelinesApi.apply(immutable);
        update({ ...getSnapshot(), operation, busy: false, error: "" });
      } catch (reason) {
        const rejected = reason instanceof ApiRequestError && reason.status !== undefined && reason.status < 500;
        update({ ...getSnapshot(), request: rejected ? undefined : immutable, busy: false, error: getErrorMessage(reason) });
      }
    },
    refresh: async (signal: AbortSignal) => {
      const id = getSnapshot().operation?.id;
      if (!id) return;
      try {
        const operation = await pipelinesApi.activation(id, signal);
        if (!signal.aborted && getSnapshot().operation?.id === id)
          update({ ...getSnapshot(), operation, error: "" });
      } catch (reason) {
        if (!signal.aborted) update({ ...getSnapshot(), error: getErrorMessage(reason) });
      }
    },
    cancel: async () => {
      if (getSnapshot().busy || !getSnapshot().operation || applyFinished(getSnapshot().operation)) return;
      update({ ...getSnapshot(), busy: true, error: "" });
      try {
        const operation = await pipelinesApi.cancel(getSnapshot().operation!.id);
        update({ ...getSnapshot(), operation, busy: false });
      } catch (reason) { update({ ...getSnapshot(), busy: false, error: getErrorMessage(reason) }); }
    },
    reset: () => {
      if (getSnapshot().busy || (getSnapshot().operation && !applyFinished(getSnapshot().operation))) return;
      update({ busy: false, error: "" });
    },
  };
}

export function usePipelineApply(key: string, onComplete: (id: string) => void) {
  const session = navigationDraft(key, () => createApplySession(key));
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const operation = snapshot.operation;
  const operationId = operation?.id;
  const finished = applyFinished(operation);
  useEffect(() => {
    if (operation?.phase === "succeeded") { session.reset(); onComplete(operation.service_id); }
  }, [operation?.phase, operation?.service_id, onComplete, session]);
  // The operation id is part of the identity so a new apply restarts polling.
  const refresh = useCallback((signal: AbortSignal) => operationId ? session.refresh(signal) : undefined, [operationId, session]);
  usePollingLoop(refresh, { enabled: !!operationId && !finished, intervalMs: 3000, overlap: "skip",
    pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true });
  return { ...snapshot, session };
}
