import { useAuth } from "@/auth/AuthContext";
import { PipelineApplyStatus } from "./PipelineApplyStatus";
import { usePipelineApply } from "./applySession";

/** Existing activation links follow the same session as the monitoring workbench. */
export function PipelineActivation({ operationId, onClose, onComplete }: {
  operationId: string;
  onClose: () => void;
  onComplete: (serviceId: string) => void;
}) {
  const { userId } = useAuth();
  const apply = usePipelineApply(`pipeline-activation:${userId}:${operationId}`, onComplete, operationId);
  return <section className="pl-activation" aria-label="Pipeline activation">
    <div className="pl-header">
      <h3>Monitoring setup</h3>
      <button type="button" onClick={onClose}>Close</button>
    </div>
    <PipelineApplyStatus apply={apply} onReset={onClose} />
  </section>;
}
