import { useCallback, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { PipelineWorkspace } from "@/types/pipelines.generated";
import type { PipelineState } from "../pipelines/diagnostics";

/** One status request for the workspace, no per-service Docker calls or telemetry subscriptions. */
export function useMonitoringServices(enabled: boolean, refreshInterval = 20_000, selectedServiceId?: string) {
  const [services, setServices] = useState<ActiveService[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [workspace, setWorkspace] = useState<PipelineWorkspace>();
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const query = selectedServiceId ? `?selected_service_id=${encodeURIComponent(selectedServiceId)}` : "";
      const next = await apiUtils.get<PipelineWorkspace>(`/v1/monitors/workspace${query}`,
        { signal, redirectOnUnauthorized: false });
      if (!Array.isArray(next.services)) throw new Error("The monitoring service list could not be read.");
      if (!signal.aborted) { setServices(next.services as unknown as ActiveService[]); setWorkspace(next); setReady(true); setError(""); }
    } catch (reason) {
      if (!signal.aborted) setError(getErrorMessage(reason));
    }
  }, [selectedServiceId]);
  const { reload, abort } = usePollingLoop(load, { enabled, intervalMs: refreshInterval, pauseWhenHidden: true, resumeOnVisible: true });
  const rename = useCallback(async (id: string, display_name: string) => {
    await apiUtils.patch(`${API_CONFIG.ENDPOINTS.MONITORING.DELETE(id)}/label`, { display_name });
    abort();
    setServices(previous => previous.map(service => service.id === id ? { ...service, display_name } : service));
    void reload();
  }, [abort, reload]);
  const remove = useCallback((id: string) => {
    abort();
    setServices(previous => previous.filter(service => service.id !== id));
  }, [abort]);
  return { services, ready, error, reload, rename, remove, authoringEnabled: workspace?.authoring_enabled ?? false, pipelineState: workspace?.selected_service_id === selectedServiceId
    // The workspace serves stored status JSON, so it stays untyped on the wire.
    ? workspace?.pipeline_state as PipelineState | null | undefined : undefined };
}
