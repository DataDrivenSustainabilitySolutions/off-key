import { useEffect, useState } from "react";
import type { PipelineDefinition, PipelineValidation } from "./contracts";
import { pipelinesApi } from "./api";

/** Inferred names come from the canonical compiler; diagnostics remain an explicit action. */
export function useGraphMetadata(
  definition: PipelineDefinition,
  enabled: boolean,
  selectedNodeId?: string,
) {
  const [snapshot, setSnapshot] = useState<{
    definition: PipelineDefinition;
    validation: PipelineValidation;
    selectedNodeId: string | undefined;
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
        } catch {
          /* Explicit Validate reports transport and compiler failures. */
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
  }, [definition, enabled, selectedNodeId]);
  return snapshot?.definition === definition &&
    snapshot.selectedNodeId === selectedNodeId
    ? snapshot.validation
    : undefined;
}
