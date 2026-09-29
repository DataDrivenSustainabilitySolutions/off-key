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
import { useParams } from "react-router-dom";

import { buildSensorClaims, mqttFiltersOverlap } from "./monitoring/config";
import { AdaptiveMonitoringSetup } from "./monitoring/AdaptiveMonitoringSetup";
import { MonitoringDataPanels } from "./monitoring/MonitoringDataPanels";
import { LaneCard } from "./monitoring/MonitoringUi";
import { StaticMonitoringSetup } from "./monitoring/StaticMonitoringSetup";
import { useMonitoringData } from "./monitoring/useMonitoringData";

function Monitoring() {
  const { chargerId = "" } = useParams<{ chargerId: string }>();
  return <ChargerMonitoring key={chargerId} chargerId={chargerId} />;
}

function ChargerMonitoring({ chargerId }: { chargerId: string }) {
  const { isAdmin } = useAuth();
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
          eyebrow="Monitoring"
          title={`Charger ${chargerId}`}
        />
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <MetricCard
            label="Sensors"
            value={sensorTypes.length}
          />
          <MetricCard
            label="Unassigned sensors"
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
            <LaneCard title="Static relationships" description="A fixed baseline with calibrated, sequential evidence." selected={selectedLane === "static_baseline"} onSelect={() => setSelectedLane("static_baseline")} icon={Database} />
            <LaneCard title="Adaptive streams" description="A model that adapts to new data, with a fixed alarm threshold." selected={selectedLane === "adaptive_stream"} onSelect={() => setSelectedLane("adaptive_stream")} icon={Activity} />
          </div>
        </SectionPanel>

        {selectedLane === "static_baseline" ? (
          <StaticMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} staticModels={staticModels} loadingModels={loadingModels} onStarted={loadServices} />
        ) : (
          <AdaptiveMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} adaptiveModels={adaptiveModels} loadingModels={loadingModels} onStarted={loadServices} />
        )}

        </>}

        <MonitoringDataPanels
          services={services}
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
