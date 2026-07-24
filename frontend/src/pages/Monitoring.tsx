import {
  MetricCard,
  PageHeader,
  PageShell,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { useFetch } from "@/dataFetch/UseFetch";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import type { Anomaly } from "@/types/charger";
import { getServiceDeleteActionDisplay } from "@/types/monitoring";
import type { ActiveService, ModelDefinition } from "@/types/monitoring";
import { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { useParams } from "react-router-dom";

import { buildSensorClaims } from "./monitoring/config";
import { MonitoringDataPanels } from "./monitoring/MonitoringDataPanels";
import { StaticMonitoringSetup } from "./monitoring/StaticMonitoringSetup";

function Monitoring() {
  const { chargerId = "" } = useParams<{ chargerId: string }>();
  const { allTelemetryMap, loadAllTelemetryTypes } = useFetch();
  const [models, setModels] = useState<Record<string, ModelDefinition>>({});
  const [services, setServices] = useState<ActiveService[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loadingServices, setLoadingServices] = useState(false);
  const [loadingAnomalies, setLoadingAnomalies] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);

  const sensorTypes = useMemo(
    () => (allTelemetryMap[chargerId] ?? []).map((entry) => entry.type),
    [allTelemetryMap, chargerId],
  );
  const staticModels = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(models).filter(
          ([, model]) => model.strategy === "static_baseline",
        ),
      ),
    [models],
  );
  const claimsBySensor = useMemo(
    () => buildSensorClaims(chargerId, sensorTypes, services),
    [chargerId, sensorTypes, services],
  );
  const chargerServices = useMemo(
    () =>
      services.filter((service) =>
        (service.mqtt_topics ?? []).some(
          (topic) =>
            topic.startsWith(`charger/${chargerId}/`) ||
            topic.startsWith("charger/+/"),
        ),
      ),
    [chargerId, services],
  );

  const loadModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const catalog = await apiUtils.get<Record<string, ModelDefinition>>(
        API_CONFIG.ENDPOINTS.MONITORING.MODELS,
      );
      setModels(catalog ?? {});
    } catch (error) {
      toast.error(
        `Failed to load static detectors: ${getErrorMessage(error)}`,
      );
    } finally {
      setLoadingModels(false);
    }
  }, []);

  const loadServices = useCallback(async () => {
    setLoadingServices(true);
    try {
      const activeServices = await apiUtils.get<ActiveService[]>(
        `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?active_only=true&include_docker_status=true`,
      );
      setServices(activeServices ?? []);
    } catch (error) {
      toast.error(`Failed to load services: ${getErrorMessage(error)}`);
    } finally {
      setLoadingServices(false);
    }
  }, []);

  const loadAnomalies = useCallback(async () => {
    if (!chargerId) return;
    setLoadingAnomalies(true);
    try {
      const recentAnomalies = await apiUtils.get<Anomaly[]>(
        API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId),
      );
      setAnomalies(recentAnomalies ?? []);
    } catch (error) {
      toast.error(`Failed to load anomalies: ${getErrorMessage(error)}`);
    } finally {
      setLoadingAnomalies(false);
    }
  }, [chargerId]);

  useEffect(() => {
    if (chargerId) void loadAllTelemetryTypes(chargerId);
  }, [chargerId, loadAllTelemetryTypes]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void loadModels();
      void loadServices();
      void loadAnomalies();
    }, 0);
    const interval = window.setInterval(() => {
      void loadServices();
      void loadAnomalies();
    }, 30_000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
    };
  }, [loadAnomalies, loadModels, loadServices]);

  const deleteService = async (service: ActiveService) => {
    const action = getServiceDeleteActionDisplay(service);
    if (!window.confirm(action.confirmation)) return;
    try {
      await apiUtils.delete(
        API_CONFIG.ENDPOINTS.MONITORING.DELETE(service.id),
        undefined,
        { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT },
      );
      toast.success(action.success);
      await loadServices();
    } catch (error) {
      toast.error(`Failed to delete service: ${getErrorMessage(error)}`);
    }
  };

  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Monitoring"
          title={`Charger ${chargerId}`}
          description="Assign stable sensor relationships to a static conformal monitor and follow its evidence over time."
        />
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <MetricCard
            label="Sensors"
            value={sensorTypes.length}
            helper="Discovered telemetry streams"
          />
          <MetricCard
            label="Available"
            value={sensorTypes.length - claimsBySensor.size}
            helper="Not assigned elsewhere"
            tone="info"
          />
          <MetricCard
            label="Services"
            value={chargerServices.length}
            helper="Active for this charger"
            tone={chargerServices.length ? "success" : "default"}
          />
          <MetricCard
            label="Alarms"
            value={anomalies.length}
            helper="Recent threshold crossings"
            tone={anomalies.length ? "warning" : "default"}
          />
        </div>

        <StaticMonitoringSetup
          chargerId={chargerId}
          sensorTypes={sensorTypes}
          claimsBySensor={claimsBySensor}
          staticModels={staticModels}
          loadingModels={loadingModels}
          onStarted={loadServices}
        />

        <MonitoringDataPanels
          services={services}
          anomalies={anomalies}
          loadingServices={loadingServices}
          loadingAnomalies={loadingAnomalies}
          onRefreshServices={() => void loadServices()}
          onRefreshAnomalies={() => void loadAnomalies()}
          onDeleteService={(service) => void deleteService(service)}
        />
      </PageShell>
    </>
  );
}

export default Monitoring;
