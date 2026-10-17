import { useEffect, useState } from "react";
import type { PipelineDefinition, PipelineValidation } from "./contracts";
import { pipelinesApi } from "./api";

/** Inferred names come from the canonical compiler; diagnostics remain an explicit action. */
export function useGraphMetadata(
  id: string,
  definition: PipelineDefinition,
  enabled: boolean,
  selectedNodeId?: string,
  revisionId?: string,
) {
  const [snapshot, setSnapshot] = useState<{
    definition: PipelineDefinition;
    validation: PipelineValidation;
    selectedNodeId: string | undefined;
    revisionId: string | undefined;
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
          let validation: PipelineValidation;
          if (revisionId) {
            if (!selectedNodeId) return;
            validation = await pipelinesApi.revisionMetadata(
              id,
              revisionId,
              definition,
              selectedNodeId,
              controller.signal,
            );
          } else {
            validation = await pipelinesApi.validate(
              id,
              definition,
              controller.signal,
              selectedNodeId,
            );
          }
          if (!controller.signal.aborted)
            setSnapshot({ definition, validation, selectedNodeId, revisionId });
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
  }, [id, definition, enabled, selectedNodeId, revisionId]);
  return snapshot?.definition === definition &&
    snapshot.selectedNodeId === selectedNodeId &&
    snapshot.revisionId === revisionId
    ? snapshot.validation
    : undefined;
}
