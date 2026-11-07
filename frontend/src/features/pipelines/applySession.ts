import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { createDraftStore, navigationDraft } from "@/lib/navigation-draft";
import type { PipelineActivationView, PipelineApplyRequest } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";

export const applyFinished = (operation?: PipelineActivationView) =>
  !!operation && ["succeeded", "failed", "cancelled"].includes(operation.phase);

/** Once the previous monitor is stopping, cancelling would leave nothing running. */
export const cancelRefused = (operation?: PipelineActivationView) =>
  !!operation?.retirement_started &&
  ["retiring", "starting", "awaiting_heartbeat"].includes(operation.phase);

export const REPLACEMENT_UNDER_WAY =
  "The previous monitor is already stopping, so this replacement can no longer be cancelled.";

type Snapshot = {
  request?: PipelineApplyRequest;
  operationId?: string;
  operation?: PipelineActivationView;
  busy: boolean;
  error: string;
};

/** An immutable request outlives navigation and uncertain network responses. */
export function createApplySession(storageKey: string, operationId?: string) {
  const { getSnapshot, subscribe, update, isCurrent } = createDraftStore<Snapshot>(storageKey, (value) => {
    const stored = value as Partial<Snapshot> | undefined;
    return { request: stored?.request, operation: stored?.operation,
      operationId: stored?.operation?.id ?? stored?.operationId ?? operationId, busy: false, error: "" };
  }, ({ request, operation, operationId }) => ({ request, operation, operationId }));
  // A mutation or a newer read retires every older response, including failures.
  let sequence = 0;
  return {
    getSnapshot,
    subscribe,
    submit: async (request?: PipelineApplyRequest) => {
      if (!isCurrent() || getSnapshot().busy || getSnapshot().operationId) return;
      const immutable = getSnapshot().request ?? request;
      if (!immutable) return;
      sequence++;
      update({ request: immutable, busy: true, error: "" });
      try {
        const operation = await pipelinesApi.apply(immutable);
        update({ ...getSnapshot(), operation, operationId: operation.id, busy: false, error: "" });
      } catch (reason) {
        const rejected = reason instanceof ApiRequestError && reason.status !== undefined && reason.status < 500;
        update({ ...getSnapshot(), request: rejected ? undefined : immutable, busy: false, error: getErrorMessage(reason) });
      }
    },
    refresh: async (signal: AbortSignal) => {
      const { operationId: id, busy, operation } = getSnapshot();
      if (!isCurrent() || !id || busy || applyFinished(operation)) return;
      const context = ++sequence;
      const active = () => !signal.aborted && context === sequence;
      try {
        const operation = await pipelinesApi.activation(id, signal);
        if (active())
          update({ ...getSnapshot(), operation, error: "" });
      } catch (reason) {
        if (active()) update({ ...getSnapshot(), error: getErrorMessage(reason) });
      }
    },
    cancel: async () => {
      const current = getSnapshot().operation;
      if (!isCurrent() || getSnapshot().busy || !current || applyFinished(current) || cancelRefused(current)) return;
      sequence++;
      update({ ...getSnapshot(), busy: true, error: "" });
      try {
        const operation = await pipelinesApi.cancel(current.id);
        update({ ...getSnapshot(), operation, busy: false });
      } catch (reason) { update({ ...getSnapshot(), busy: false, error: getErrorMessage(reason) }); }
    },
    reset: () => {
      if (getSnapshot().busy || (getSnapshot().operationId && !applyFinished(getSnapshot().operation))) return;
      sequence++;
      update({ busy: false, error: "" });
    },
  };
}

export function usePipelineApply(key: string, onComplete: (id: string) => void, initialOperationId?: string) {
  const session = navigationDraft(key, () => createApplySession(key, initialOperationId));
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const operation = snapshot.operation;
  const operationId = snapshot.operationId;
  const finished = applyFinished(operation);
  const notified = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (operation?.phase !== "succeeded" || notified.current === operation.id) return;
    notified.current = operation.id;
    // A workbench can start again; an existing link keeps its terminal result.
    if (!initialOperationId) session.reset();
    onComplete(operation.monitor_id);
  }, [operation?.id, operation?.phase, operation?.monitor_id, initialOperationId, onComplete, session]);
  // The operation id is part of the identity so a new apply restarts polling.
  const refresh = useCallback((signal: AbortSignal) => operationId ? session.refresh(signal) : undefined, [operationId, session]);
  usePollingLoop(refresh, { enabled: !!operationId && !finished, intervalMs: 3000, overlap: "skip",
    pauseWhenHidden: true, resumeOnVisible: true, startImmediately: true });
  return { ...snapshot, session };
}
