import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { buildDeviceTelemetryChargerFilter } from "@/lib/mqtt-topics";
import { getServiceDeleteActionDisplay } from "@/types/monitoring";
import type { ActiveService } from "@/types/monitoring";
import type { MonitoringStrategy } from "@/types/monitoring";
import { useAuth } from "@/auth/AuthContext";
import { Activity, Database } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useSystemDocument } from "@/features/catalogue/useSystemDocument";
import { Button } from "@/components/ui/button";

import { buildSensorClaims, mqttFiltersOverlap } from "./monitoring/config";
import { AdaptiveMonitoringSetup } from "./monitoring/AdaptiveMonitoringSetup";
import { MonitoringDataPanels } from "./monitoring/MonitoringDataPanels";
import { LaneCard } from "./monitoring/MonitoringUi";
import { StaticMonitoringSetup } from "./monitoring/StaticMonitoringSetup";
import { useMonitoringData } from "./monitoring/useMonitoringData";

function Monitoring() {
  const { chargerId = "" } = useParams<{ chargerId: string }>();
  const [params] = useSearchParams();
  const initialReading = params.get("reading") ?? undefined;
  return <ChargerMonitoring key={`${chargerId}:${initialReading ?? ""}`} chargerId={chargerId} initialReading={initialReading} />;
}

function ChargerMonitoring({ chargerId, initialReading }: { chargerId: string; initialReading?: string }) {
  const { isAdmin, isAuthenticated, userId } = useAuth();
  const catalogue = useSystemDocument({ isAuthenticated, accountKey: userId });
  const sensorLabels = useMemo(() => new Map((catalogue.document?.streams ?? []).flatMap((stream) => {
    const binding = catalogue.snapshot?.runtime.bindings?.[stream.id];
    return binding?.entity_id === chargerId ? [[binding.telemetry_key, stream.label] as const] : [];
  })), [catalogue.document, catalogue.snapshot, chargerId]);
  const entityName = useMemo(() => {
    const stream = catalogue.document?.streams.find((item) => catalogue.snapshot?.runtime.bindings?.[item.id]?.entity_id === chargerId);
    return catalogue.document?.devices.find((item) => item.id === stream?.device_id)?.label
      ?? catalogue.document?.connections.find((item) => item.id === stream?.connection_id)?.label;
  }, [catalogue.document, catalogue.snapshot, chargerId]);
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
          title={`Monitoring · ${entityName ?? chargerId}`}
          actions={
            <Button variant="ghost" asChild>
              <Link to="/entities">Entities</Link>
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
    </>
  );
}

export default Monitoring;
