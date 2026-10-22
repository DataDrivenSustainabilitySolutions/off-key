import { pipelinesApi } from "@/features/pipelines/api";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import type { MonitoringStartRequest } from "@/types/monitoring";
import type { PipelineActivationView } from "@/types/pipelines.generated";

type Phase = PipelineActivationView["phase"];

// The service row exists once its workload is created.
const STARTED: Phase[] = ["awaiting_heartbeat", "succeeded"];
const STOPPED: Phase[] = ["failed", "cancelled"];

const delay = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

/** Form monitors run as pipelines; resolve once the new service exists. */
export async function startFormMonitor(
  request: MonitoringStartRequest & { display_name?: string },
  pollMilliseconds = 1000,
): Promise<string> {
  const accepted = await apiUtils.post<{ service_id: string; activation_id: string }>(
    API_CONFIG.ENDPOINTS.MONITORING.START,
    request,
  );
  const deadline = Date.now() + API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT;
  while (Date.now() < deadline) {
    const activation = await pipelinesApi.activation(accepted.activation_id);
    if (STARTED.includes(activation.phase)) return activation.service_id;
    if (STOPPED.includes(activation.phase)) {
      throw new Error(activation.error ?? `Monitoring start was ${activation.phase}`);
    }
    await delay(pollMilliseconds);
  }
  throw new Error("Monitoring service did not start in time");
}
