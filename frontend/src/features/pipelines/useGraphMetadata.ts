import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineDefinition, PipelineValidation } from "./contracts";
import { pipelinesApi } from "./api";

/** The canonical compiler checks every edit shortly after it is made; a failed
 * check is reported with a retry instead of leaving the last result on screen. */
export function useGraphMetadata(
  definition: PipelineDefinition,
  enabled: boolean,
  selectedNodeId?: string,
) {
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    definition: PipelineDefinition;
    selectedNodeId: string | undefined;
    validation?: PipelineValidation;
    error?: string;
  }>();
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: number;
    const schedule = () => {
      clearTimeout(timer);
      if (document.hidden) return;
      timer = window.setTimeout(async () => {
        try {
          const validation = await pipelinesApi.validate(
            definition,
            controller.signal,
            selectedNodeId,
          );
          if (!controller.signal.aborted)
            setSnapshot({ definition, validation, selectedNodeId });
        } catch (reason) {
          if (!controller.signal.aborted)
            setSnapshot({ definition, selectedNodeId, error: getErrorMessage(reason) });
        }
      }, 800);
    };
    schedule();
    document.addEventListener("visibilitychange", schedule);
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [definition, enabled, selectedNodeId, attempt]);
  const current = snapshot?.definition === definition &&
    snapshot.selectedNodeId === selectedNodeId
    ? snapshot
    : undefined;
  return {
    validation: current?.validation,
    error: current?.error,
    retry: () => {
      setSnapshot(undefined);
      setAttempt((value) => value + 1);
    },
  };
}
