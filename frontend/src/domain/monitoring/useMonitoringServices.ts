import { createContext, useCallback, useContext, useEffect, useId, useState } from "react";
import { usePollingLoop } from "@/hooks/use-polling";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { PipelineRuntimeState, PipelineWorkspace } from "@/types/pipelines.generated";

export type Registration = { intervalMs: number; selectedServiceId?: string };

/** One status request for the workspace, no per-service Docker calls or telemetry subscriptions. */
export function useWorkspacePoll(enabled: boolean, refreshInterval: number, selectedServiceId?: string) {
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
  return { services, setServices, ready, error, workspace, reload, abort };
}

export type Feed = ReturnType<typeof useWorkspacePoll> & { register: (id: string, registration: Registration) => () => void };
export const FeedContext = createContext<Feed | null>(null);

/** The workspace's service list; outside the provider it polls on its own. */
export function useMonitoringServices(enabled: boolean, refreshInterval = 20_000, selectedServiceId?: string) {
  const feed = useContext(FeedContext);
  const own = useWorkspacePoll(!feed && enabled, refreshInterval, selectedServiceId);
  const source = feed ?? own;
  const id = useId();
  const register = feed?.register;
  useEffect(() => {
    if (register && enabled) return register(id, { intervalMs: refreshInterval, selectedServiceId });
  }, [register, enabled, id, refreshInterval, selectedServiceId]);
  const { setServices, abort, reload, workspace } = source;
  const rename = useCallback(async (serviceId: string, display_name: string) => {
    await apiUtils.patch(`${API_CONFIG.ENDPOINTS.MONITORING.DELETE(serviceId)}/label`, { display_name });
    abort();
    setServices(previous => previous.map(service => service.id === serviceId ? { ...service, display_name } : service));
    void reload();
  }, [abort, reload, setServices]);
  const remove = useCallback((serviceId: string) => {
    abort();
    setServices(previous => previous.filter(service => service.id !== serviceId));
  }, [abort, setServices]);
  return { services: source.services, ready: source.ready, error: source.error, reload, rename, remove,
    authoringEnabled: workspace?.authoring_enabled ?? false,
    pipelineState: workspace?.selected_service_id === selectedServiceId
      // The workspace serves stored status JSON, so it stays untyped on the wire.
      ? workspace?.pipeline_state as PipelineRuntimeState | null | undefined : undefined };
}
