import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import { pipelinesApi } from "./api";
import type { PipelineDefinition, PipelineValidation } from "./contracts";

/** Focused metadata never replaces an immutable graph or an unsaved arrangement. */
export function useRunMetadata(
  serviceId: string,
  selectedNodeId?: string,
  definition?: PipelineDefinition,
) {
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    serviceId: string;
    selectedNodeId: string;
    validation?: PipelineValidation | null;
    error?: string;
  }>();
  useEffect(() => {
    if (!selectedNodeId || !definition) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const validation = await pipelinesApi.runMetadata(
          serviceId,
          definition,
          selectedNodeId,
          controller.signal,
        );
        if (!controller.signal.aborted)
          setSnapshot({
            serviceId,
            selectedNodeId,
            validation,
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
  }, [serviceId, selectedNodeId, definition, attempt]);
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
