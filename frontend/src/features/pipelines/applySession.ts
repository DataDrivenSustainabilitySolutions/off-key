import { useEffect, useSyncExternalStore } from "react";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { navigationDraft, navigationDraftGeneration, readStoredDraft, storeDraft } from "@/lib/navigation-draft";
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
  const generation = navigationDraftGeneration();
  const stored = readStoredDraft(storageKey) as Partial<Snapshot> | undefined;
  let snapshot: Snapshot = {
    request: stored?.request, operation: stored?.operation, busy: false, error: "",
  };
  const listeners = new Set<() => void>();
  const update = (next: Snapshot) => {
    if (generation !== navigationDraftGeneration()) return;
    snapshot = next;
    storeDraft(storageKey, { request: next.request, operation: next.operation });
    listeners.forEach((listener) => listener());
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    submit: async (request?: PipelineApplyRequest) => {
      if (snapshot.busy || snapshot.operation) return;
      const immutable = snapshot.request ?? request;
      if (!immutable) return;
      update({ request: immutable, busy: true, error: "" });
      try {
        const operation = await pipelinesApi.apply(immutable);
        update({ ...snapshot, operation, busy: false, error: "" });
      } catch (reason) {
        const rejected = reason instanceof ApiRequestError && reason.status !== undefined && reason.status < 500;
        update({ ...snapshot, request: rejected ? undefined : immutable, busy: false, error: getErrorMessage(reason) });
      }
    },
    refresh: async (signal: AbortSignal) => {
      const id = snapshot.operation?.id;
      if (!id) return;
      try {
        const operation = await pipelinesApi.activation(id, signal);
        if (!signal.aborted && snapshot.operation?.id === id)
          update({ ...snapshot, operation, error: "" });
      } catch (reason) {
        if (!signal.aborted) update({ ...snapshot, error: getErrorMessage(reason) });
      }
    },
    cancel: async () => {
      if (snapshot.busy || !snapshot.operation || applyFinished(snapshot.operation)) return;
      update({ ...snapshot, busy: true, error: "" });
      try {
        const operation = await pipelinesApi.cancel(snapshot.operation!.id);
        update({ ...snapshot, operation, busy: false });
      } catch (reason) { update({ ...snapshot, busy: false, error: getErrorMessage(reason) }); }
    },
    reset: () => {
      if (snapshot.busy || (snapshot.operation && !applyFinished(snapshot.operation))) return;
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
  useEffect(() => {
    if (!operationId || finished) return;
    const controller = new AbortController();
    let polling = false;
    const poll = async () => {
      if (document.hidden || polling) return;
      polling = true;
      try { await session.refresh(controller.signal); } finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    document.addEventListener("visibilitychange", poll);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", poll); };
  }, [operationId, finished, session]);
  return { ...snapshot, session };
}
