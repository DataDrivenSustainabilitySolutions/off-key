import { useCallback, useEffect, useRef, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import type { ActiveService } from "@/types/monitoring";
import type { PipelineWorkspace } from "@/types/pipelines.generated";

/** One status request for the workspace, no per-service Docker calls or telemetry subscriptions. */
export function useMonitoringServices(enabled: boolean, refreshInterval = 20_000, selectedServiceId?: string) {
  const [services, setServices] = useState<ActiveService[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [workspace, setWorkspace] = useState<PipelineWorkspace>();
  const active = useRef(false);
  const request = useRef<AbortController | undefined>(undefined);
  const reload = useCallback(async () => {
    if (!active.current) return;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    try {
      const query = selectedServiceId ? `?selected_service_id=${encodeURIComponent(selectedServiceId)}` : "";
      const next = await apiUtils.get<PipelineWorkspace>(`/v1/monitors/workspace${query}`,
        { signal: controller.signal, redirectOnUnauthorized: false });
      if (!Array.isArray(next.services)) throw new Error("The monitoring service list could not be read.");
      if (!controller.signal.aborted) { setServices(next.services as unknown as ActiveService[]); setWorkspace(next); setReady(true); setError(""); }
    } catch (reason) {
      if (!controller.signal.aborted) setError(getErrorMessage(reason));
    }
  }, [selectedServiceId]);
  useEffect(() => {
    if (!enabled) return;
    active.current = true;
    const initial = setTimeout(() => void reload(), 0);
    const timer = setInterval(() => { if (!document.hidden) void reload(); }, refreshInterval);
    const visible = () => { if (!document.hidden) void reload(); };
    document.addEventListener("visibilitychange", visible);
    return () => { active.current = false; clearTimeout(initial); clearInterval(timer); request.current?.abort(); document.removeEventListener("visibilitychange", visible); };
  }, [enabled, refreshInterval, reload]);
  const rename = useCallback(async (id: string, display_name: string) => {
    await apiUtils.patch(`${API_CONFIG.ENDPOINTS.MONITORING.DELETE(id)}/label`, { display_name });
    request.current?.abort();
    if (active.current) setServices(previous => previous.map(service => service.id === id ? { ...service, display_name } : service));
    void reload();
  }, [reload]);
  const remove = useCallback((id: string) => {
    request.current?.abort();
    setServices(previous => previous.filter(service => service.id !== id));
  }, []);
  return { services, ready, error, reload, rename, remove, authoringEnabled: workspace?.authoring_enabled ?? false, pipelineState: workspace?.selected_service_id === selectedServiceId ? workspace?.pipeline_state : undefined };
}
