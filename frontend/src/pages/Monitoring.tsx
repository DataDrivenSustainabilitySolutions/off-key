import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { buildDeviceTelemetryChargerFilter } from "@/lib/mqtt-topics";
import { getServiceDeleteActionDisplay } from "@/types/monitoring";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringStrategy } from "@/types/monitoring";
import { useAuth } from "@/auth/AuthContext";
import { Activity, Database } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { entityStreams } from "@/domain/system/entityStreams";
import { useSystemDocument } from "@/domain/system/useSystemDocument";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/hooks/use-confirm";
import { useDocumentTitle } from "@/hooks/use-document-title";

import { buildSensorClaims, mqttFiltersOverlap } from "@/lib/monitoring-services";
import { AdaptiveMonitoringSetup } from "@/features/monitoring/setup/AdaptiveMonitoringSetup";
import { MonitoringDataPanels } from "./monitoring/MonitoringDataPanels";
import { LaneCard } from "./monitoring/MonitoringUi";
import { StaticMonitoringSetup } from "@/features/monitoring/setup/StaticMonitoringSetup";
import { useMonitoringData } from "./monitoring/useMonitoringData";
import type { PipelineWorkspace } from "@/types/pipelines.generated";
import { useOptionalCatalogue } from "@/features/workspace/catalogue-context";

function Monitoring() {
  const { chargerId = "" } = useParams<{ chargerId: string }>();
  const [params] = useSearchParams();
  const initialReading = params.get("reading") ?? undefined;
  const catalogue = useOptionalCatalogue();
  // Undecided until the workspace answers, so the legacy page never fetches
  // before an authoring redirect; an unavailable workspace keeps the legacy page.
  const [graphAuthoring, setGraphAuthoring] = useState<boolean>();
  useEffect(() => {
    const controller = new AbortController();
    void apiUtils.get<PipelineWorkspace>("/v1/monitors/workspace", { signal: controller.signal, redirectOnUnauthorized: false })
      .then(
        snapshot => { if (!controller.signal.aborted) setGraphAuthoring(snapshot?.authoring_enabled === true); },
        () => { if (!controller.signal.aborted) setGraphAuthoring(false); },
      );
    return () => controller.abort();
  }, []);
  if (graphAuthoring === undefined) return <p role="status">Loading monitoring…</p>;
  if (graphAuthoring) {
    const readingId = Object.entries(catalogue?.system.snapshot?.runtime.bindings ?? {}).find(([id, binding]) => binding.entity_id === chargerId && (id === initialReading || binding.telemetry_key === initialReading))?.[0] ?? initialReading;
    if (initialReading && catalogue?.system.status === "loading") return <p role="status">Resolving monitoring inputs…</p>;
    return <Navigate replace to={`/?create=monitoring&target=${encodeURIComponent(chargerId)}${readingId ? `&reading=${encodeURIComponent(readingId)}` : ""}`} />;
  }
  return <ChargerMonitoring key={`${chargerId}:${initialReading ?? ""}`} chargerId={chargerId} initialReading={initialReading} />;
}

function ChargerMonitoring({ chargerId, initialReading }: { chargerId: string; initialReading?: string }) {
  const { isAdmin, isAuthenticated, userId } = useAuth();
  const [confirm, confirmation] = useConfirm();
  // Inside the workspace the provider's catalogue is reused; standalone mounts load their own.
  const provided = useOptionalCatalogue();
  const own = useSystemDocument({ isAuthenticated: isAuthenticated && !provided, accountKey: userId });
  const catalogue = provided?.system ?? own;
  const streams = useMemo(() => entityStreams(catalogue.document, catalogue.snapshot?.runtime, chargerId),
    [catalogue.document, catalogue.snapshot, chargerId]);
  const sensorLabels = useMemo(() => new Map([...streams].map(([key, stream]) => [key, stream.label] as const)), [streams]);
  const entityName = useMemo(() => {
    const stream = streams.values().next().value;
    return catalogue.document?.devices.find((item) => item.id === stream?.device_id)?.label
      ?? catalogue.document?.connections.find((item) => item.id === stream?.connection_id)?.label;
  }, [catalogue.document, streams]);
  useDocumentTitle(entityName ?? chargerId, "Monitoring");
  const data = useMonitoringData(chargerId);
  const sensorTypes = data.sensors.data;
  const models = data.models.data;
  const services = data.services.data;
  const anomalies = data.anomalies.data;
  const loadingServices = data.services.loading;
  const loadingAnomalies = data.anomalies.loading;
  const loadingModels = data.models.loading;
  const loadServices = data.services.reload;
  const loadAnomalies = data.anomalies.reload;
  const [selectedLane, setSelectedLane] = useState<MonitoringStrategy>("static_baseline");

  const staticModels = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(models).filter(
          ([, model]) => model.strategy === "static_baseline",
        ),
      ),
    [models],
  );
  const adaptiveModels = useMemo(
    () => Object.fromEntries(Object.entries(models).filter(([, model]) => model.strategy === "adaptive_stream")),
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
            mqttFiltersOverlap(
              topic,
              buildDeviceTelemetryChargerFilter(chargerId),
            ),
        ),
      ),
    [chargerId, services],
  );

  const deleteService = async (service: ActiveService) => {
    const action = getServiceDeleteActionDisplay(service);
    const label = action.ariaLabel[0]!.toUpperCase() + action.ariaLabel.slice(1);
    if (!await confirm({ title: action.confirmation, description: "Collected history is retained.", confirmLabel: label, destructive: true })) return;
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
      <PageShell>
        <PageHeader
          title={`Monitoring · ${entityName ?? chargerId}`}
          actions={
            <Button variant="ghost" asChild>
              <Link to="/sources">Sources</Link>
            </Button>
          }
        />
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <MetricCard
            label="Readings"
            value={sensorTypes.length}
          />
          <MetricCard
            label="Available readings"
            value={sensorTypes.length - claimsBySensor.size}
            tone="info"
          />
          <MetricCard
            label="Services"
            value={chargerServices.length}
            tone={chargerServices.length ? "success" : "default"}
          />
          <MetricCard
            label="Alarms"
            value={anomalies.length}
            tone={anomalies.length ? "warning" : "default"}
          />
        </div>

        {isAdmin && <>
        <SectionPanel title="Monitoring mode">
          <div className="grid gap-4 lg:grid-cols-2">
            <LaneCard title="Static baseline" selected={selectedLane === "static_baseline"} onSelect={() => setSelectedLane("static_baseline")} icon={Database} />
            <LaneCard title="Adaptive stream" selected={selectedLane === "adaptive_stream"} onSelect={() => setSelectedLane("adaptive_stream")} icon={Activity} />
          </div>
        </SectionPanel>

        {selectedLane === "static_baseline" ? (
          <StaticMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} staticModels={staticModels} loadingModels={loadingModels} onStarted={loadServices} initialReading={initialReading} sensorLabels={sensorLabels} />
        ) : (
          <AdaptiveMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} adaptiveModels={adaptiveModels} loadingModels={loadingModels} onStarted={loadServices} initialReading={initialReading} sensorLabels={sensorLabels} />
        )}

        </>}

        <MonitoringDataPanels
          services={chargerServices}
          anomalies={anomalies}
          loadingServices={loadingServices}
          loadingAnomalies={loadingAnomalies}
          onRefreshServices={() => void loadServices()}
          onRefreshAnomalies={() => void loadAnomalies()}
          onDeleteService={isAdmin ? (service) => void deleteService(service) : undefined}
        />
      </PageShell>
      {confirmation}
    </>
  );
}

export default Monitoring;
