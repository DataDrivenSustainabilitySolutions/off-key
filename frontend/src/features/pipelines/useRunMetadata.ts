import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import { pipelinesApi } from "./api";
import type { PipelineValidation } from "./contracts";

/** Focused metadata never replaces an immutable graph or an unsaved arrangement. */
export function useRunMetadata(serviceId: string, selectedNodeId?: string) {
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    serviceId: string;
    selectedNodeId: string;
    validation?: PipelineValidation | null;
    error?: string;
  }>();
  useEffect(() => {
    if (!selectedNodeId) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const view = await pipelinesApi.service(
          serviceId,
          controller.signal,
          selectedNodeId,
        );
        if (!controller.signal.aborted)
          setSnapshot({
            serviceId,
            selectedNodeId,
            validation: view.validation,
          });
      } catch (reason) {
        if (!controller.signal.aborted)
          setSnapshot({
            serviceId,
            selectedNodeId,
            error: getErrorMessage(reason),
          });
      }
    }, 200);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [serviceId, selectedNodeId, attempt]);
  const current =
    snapshot?.serviceId === serviceId &&
    snapshot.selectedNodeId === selectedNodeId
      ? snapshot
      : undefined;
  return {
    validation: current?.validation,
    error: current?.error,
    retry: () => setAttempt((value) => value + 1),
  };
}
