import { useCallback, useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getTelemetryTypes } from "@/lib/charger-api";
import { getErrorMessage } from "@/lib/errors";
import type { Anomaly } from "@/types/charger";
import type { ActiveService, ModelDefinition } from "@/types/monitoring";

function useMonitoringResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  initial: T,
  errorLabel: string,
  pollInterval?: number,
) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(false);
  const active = useRef(false);
  const request = useRef<AbortController | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const reload = useCallback(async (): Promise<void> => {
    if (!active.current) return;
    clearTimeout(timer.current);
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const result = await load(controller.signal);
      if (!controller.signal.aborted) setData(result);
    } catch (error) {
      if (!controller.signal.aborted) {
        toast.error(`${errorLabel}: ${getErrorMessage(error)}`);
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        if (pollInterval) {
          timer.current = setTimeout(() => void reload(), pollInterval);
        }
      }
    }
  }, [errorLabel, load, pollInterval]);

  useEffect(() => {
    active.current = true;
    timer.current = setTimeout(() => void reload(), 0);
    return () => {
      active.current = false;
      clearTimeout(timer.current);
      request.current?.abort();
    };
  }, [reload]);

  return { data, loading, reload };
}

export function useMonitoringData(chargerId: string) {
  const loadSensors = useCallback(
    (signal: AbortSignal) => getTelemetryTypes(chargerId, signal),
    [chargerId],
  );
  const loadModels = useCallback(
    (signal: AbortSignal) => apiUtils.get<Record<string, ModelDefinition>>(
      API_CONFIG.ENDPOINTS.MONITORING.MODELS, { signal },
    ), [],
  );
  const loadServices = useCallback(
    (signal: AbortSignal) => apiUtils.get<ActiveService[]>(
      `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?active_only=true&include_docker_status=true`,
      { signal },
    ), [],
  );
  const loadAnomalies = useCallback(
    (signal: AbortSignal) => apiUtils.get<Anomaly[]>(
      API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId), { signal },
    ), [chargerId],
  );

  return {
    sensors: useMonitoringResource(loadSensors, [], "Failed to load telemetry types"),
    models: useMonitoringResource(loadModels, {}, "Failed to load detectors"),
    services: useMonitoringResource(loadServices, [], "Failed to load services", 30_000),
    anomalies: useMonitoringResource(loadAnomalies, [], "Failed to load anomalies", 30_000),
  };
}
