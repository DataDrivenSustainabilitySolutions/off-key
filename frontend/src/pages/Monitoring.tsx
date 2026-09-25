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
          description="Assign exclusive telemetry relationships to a static conformal or continuously adapting stream monitor."
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

        <SectionPanel title="Choose a monitoring lane" description="Static monitoring freezes its fitted detector; adaptive monitoring learns after every score.">
          <div className="grid gap-4 lg:grid-cols-2">
            <LaneCard title="Static relationships" eyebrow="Conformal evidence" description="Train once, calibrate p-values, then accumulate sequential martingale evidence." selected={selectedLane === "static_baseline"} onSelect={() => setSelectedLane("static_baseline")} icon={Database} />
            <LaneCard title="Adaptive streams" eyebrow="Aberrant · 24 detectors" description="Warm up, calibrate a fixed score threshold, then score before learning each new point." selected={selectedLane === "adaptive_stream"} onSelect={() => setSelectedLane("adaptive_stream")} icon={Activity} />
          </div>
        </SectionPanel>

        {selectedLane === "static_baseline" ? (
          <StaticMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} staticModels={staticModels} loadingModels={loadingModels} onStarted={loadServices} />
        ) : (
          <AdaptiveMonitoringSetup chargerId={chargerId} sensorTypes={sensorTypes} claimsBySensor={claimsBySensor} adaptiveModels={adaptiveModels} loadingModels={loadingModels} onStarted={loadServices} />
        )}

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
