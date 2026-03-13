import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { NavigationBar } from "@/components/NavigationBar";
import { useParams } from "react-router-dom";
import { useFetch } from "@/dataFetch/UseFetch";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import toast from "react-hot-toast";
import { ChevronUp, ChevronDown } from "lucide-react";
import { getStatusDisplay } from "@/types/monitoring";
import { formatAnomalyZScore, getAnomalyZScoreClassName } from "@/lib/anomaly-semantics";

// Helper function to parse numeric input, preventing NaN storage
const parseNumericInput = (
  rawValue: string,
  schemaType?: string
): string | number => {
  if (rawValue === "") return "";

  if (schemaType === "integer" || schemaType === "number") {
    const parsed =
      schemaType === "integer" ? parseInt(rawValue, 10) : parseFloat(rawValue);
    return Number.isNaN(parsed) ? "" : parsed;
  }

  return rawValue;
};

const parseTopicPatterns = (raw: string): string[] => {
  return raw
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
};

interface ActiveService {
  id: string;
  container_id: string;
  container_name: string;
  mqtt_topics: string[];
  status: boolean;
  docker_status?: string; // Actual Docker container status
  created_at?: string;
}

interface Anomaly {
  charger_id: string;
  timestamp: string;
  telemetry_type: string;
  anomaly_type: string;
  anomaly_value: number;
}

type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";

type PerformanceConfigState = {
  heuristic_enabled: boolean;
  heuristic_window_size: number;
  heuristic_min_samples: number;
  heuristic_zscore_threshold: number;
  sensor_key_strategy: SensorKeyStrategy;
  sensor_freshness_seconds: number;
};

type PreprocessingStepConfig = {
  id: string;
  type: string;
  params: Record<string, any>;
};

const PreprocessingSection: React.FC<{
  steps: PreprocessingStepConfig[];
  availablePreprocessors: Record<string, any>;
  newPreprocessorType: string;
  isLoading: boolean;
  onSelectType: (type: string) => void;
  onAdd: () => void;
  onParamChange: (index: number, key: string, rawValue: string, schemaType?: string) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
  onRemove: (index: number) => void;
}> = ({
  steps,
  availablePreprocessors,
  newPreprocessorType,
  isLoading,
  onSelectType,
  onAdd,
  onParamChange,
  onMoveUp,
  onMoveDown,
  onRemove,
}) => (
  <div className="mt-10">
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-md font-semibold">Preprocessing (optional)</h3>
      {isLoading && <span className="text-xs text-gray-500">Loading...</span>}
    </div>
    <div className="flex gap-2 items-center mb-3">
      <select
        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
        value={newPreprocessorType}
        onChange={(e) => onSelectType(e.target.value)}
        disabled={isLoading}
      >
        <option value="">Add step...</option>
        {Object.keys(availablePreprocessors).map((key) => (
          <option key={key} value={key}>
            {key}
          </option>
        ))}
      </select>
      <Button
        className="bg-indigo-800 hover:bg-indigo-700"
        disabled={!newPreprocessorType || isLoading}
        onClick={onAdd}
      >
        Add
      </Button>
    </div>

    {steps.length === 0 && <p className="text-sm text-gray-500">No preprocessing steps selected.</p>}

    <div className="space-y-4">
      {steps.map((step, index) => {
        const schemaProps = availablePreprocessors[step.type]?.parameters?.properties || {};
        return (
          <div key={step.id} className="border rounded p-3 bg-gray-50 dark:bg-neutral-900">
            <div className="flex items-center justify-between">
              <div className="font-semibold">
                {index + 1}. {step.type}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onMoveUp(index)}
                  disabled={index === 0}
                  title="Move up"
                >
                  <ChevronUp className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onMoveDown(index)}
                  disabled={index === steps.length - 1}
                  title="Move down"
                >
                  <ChevronDown className="h-4 w-4" />
                </Button>
                <Button variant="destructive" size="sm" onClick={() => onRemove(index)}>
                  Remove
                </Button>
              </div>
            </div>
            <div className="mt-3 space-y-3">
              {Object.entries(schemaProps).length === 0 && (
                <p className="text-sm text-gray-500">No parameters.</p>
              )}
              {Object.entries(schemaProps).map(([key, schema]: [string, any]) => (
                <div key={key} className="flex flex-col">
                  <label className="text-sm font-medium mb-1">
                    {key}
                    {schema?.description ? (
                      <span className="text-xs text-gray-500 ml-1">({schema.description})</span>
                    ) : null}
                  </label>
                  <input
                    type={schema?.type === "integer" || schema?.type === "number" ? "number" : "text"}
                    className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                    value={step.params?.[key] ?? ""}
                    onChange={(e) => onParamChange(index, key, e.target.value, schema?.type)}
                    min={schema?.minimum}
                    max={schema?.maximum}
                    step="any"
                  />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  </div>
);

const ActiveServicesSection: React.FC<{
  services: ActiveService[];
  isLoading: boolean;
  chargerId?: string;
  onDelete: (containerName: string) => void | Promise<void>;
}> = ({ services, isLoading, chargerId, onDelete }) => {
  const extractChargerIdFromContainer = (containerName: string): string => {
    const match = containerName.match(/^radar-(.+)-\d+$/);
    return match ? match[1] : "Unknown";
  };

  const chargerSpecificServices = React.useMemo(() => {
    if (!chargerId) return services;
    return services.filter((service) => extractChargerIdFromContainer(service.container_name) === chargerId);
  }, [services, chargerId]);

  return (
    <div className="flex mt-5">
      <Card className="ml-16 bg-white shadow-md w-11/12 min-h-96 dark:bg-neutral-950">
        <CardTitle className="ml-5 mt-4">Active Monitoring Services for Charger {chargerId}</CardTitle>
        <CardContent>
          <div className="mt-4">
            {isLoading ? (
              <div className="flex justify-center items-center py-8">
                <div className="text-gray-500">Loading active services...</div>
              </div>
            ) : chargerSpecificServices.length === 0 ? (
              <div className="flex justify-center items-center py-8">
                <div className="text-gray-500">No active monitoring services found for charger {chargerId}</div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Container Name</TableHead>
                      <TableHead>Charger ID</TableHead>
                      <TableHead>MQTT Topics</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created At</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {chargerSpecificServices.map((service) => (
                      <TableRow key={service.id}>
                        <TableCell className="font-medium">{service.container_name}</TableCell>
                        <TableCell>{extractChargerIdFromContainer(service.container_name)}</TableCell>
                        <TableCell>
                          <div className="max-w-xs truncate" title={service.mqtt_topics.join(", ")}>
                            {service.mqtt_topics.length > 0
                              ? service.mqtt_topics.slice(0, 2).join(", ") +
                                (service.mqtt_topics.length > 2 ? ` +${service.mqtt_topics.length - 2} more` : "")
                              : "No topics"}
                          </div>
                        </TableCell>
                        <TableCell>
                          {(() => {
                            const statusDisplay = getStatusDisplay(service.docker_status, service.status);
                            return (
                              <span
                                className={`px-2 py-1 rounded-full text-xs font-medium ${statusDisplay.className}`}
                              >
                                {statusDisplay.label}
                              </span>
                            );
                          })()}
                        </TableCell>
                        <TableCell>
                          {service.created_at ? new Date(service.created_at).toLocaleString() : "Unknown"}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => onDelete(service.container_name)}
                            className="bg-red-600 hover:bg-red-700"
                          >
                            Delete
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

const AnomaliesSection: React.FC<{
  anomalies: Anomaly[];
  isLoading: boolean;
  chargerId?: string;
  onRefresh: () => void;
}> = ({ anomalies, isLoading, chargerId, onRefresh }) => (
  <div className="flex mt-5 mb-5">
    <Card className="ml-16 bg-white shadow-md w-11/12 min-h-96 dark:bg-neutral-950">
      <CardTitle className="ml-5 mt-4">Detected Anomalies for Charger {chargerId}</CardTitle>
      <CardContent>
        <div className="mt-4">
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-gray-500">{anomalies.length} anomalies detected</span>
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={isLoading}>
              {isLoading ? "Refreshing..." : "Refresh"}
            </Button>
          </div>
          {isLoading ? (
            <div className="flex justify-center items-center py-8">
              <div className="text-gray-500">Loading anomalies...</div>
            </div>
          ) : anomalies.length === 0 ? (
            <div className="flex justify-center items-center py-8">
              <div className="text-gray-500">No anomalies detected for charger {chargerId}</div>
            </div>
          ) : (
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <Table>
                  <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Telemetry Type</TableHead>
                    <TableHead>Anomaly Type</TableHead>
                    <TableHead>Z-Score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {anomalies.slice(0, 50).map((anomaly, index) => (
                    <TableRow key={`${anomaly.timestamp}-${index}`}>
                      <TableCell className="font-medium">{new Date(anomaly.timestamp).toLocaleString()}</TableCell>
                      <TableCell>
                        <span className="px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                          {anomaly.telemetry_type}
                        </span>
                      </TableCell>
                      <TableCell>{anomaly.anomaly_type}</TableCell>
                      <TableCell>
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-medium ${getAnomalyZScoreClassName(
                            anomaly.anomaly_value
                          )}`}
                        >
                          {formatAnomalyZScore(anomaly.anomaly_value)}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {anomalies.length > 50 && (
                <div className="text-center py-2 text-sm text-gray-500">Showing 50 of {anomalies.length} anomalies</div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  </div>
);

const Monitoring: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  //map where keys and the boolean are safed for the dropbox checked or not checked symbole
  const [visibleMap, setVisibleMap] = useState<Record<string, boolean>>({});
  //Data from useFetch
  const { allTelemetryMap, loadAllTelemetryTypes } = useFetch();
  //Caching mechanism to avoid unneccesary fetches
  const monitoringKeys = useMemo(
    () => {
      const telemetryData = allTelemetryMap[chargerId!] || [];
      return telemetryData.map(item => item.type);
    },
    [allTelemetryMap, chargerId]
  );
  const activeKeys = useMemo(
    () =>
      Object.entries(visibleMap)
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        .filter(([_, visible]) => visible)
        .map(([key]) => key),
    [visibleMap]
  );
  const [topicMode, setTopicMode] = useState<"selected_sensors" | "direct_patterns">(
    "selected_sensors"
  );
  const [topicPatternInput, setTopicPatternInput] = useState<string>("");
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<string | null>(
    null
  );
  const [availableModels, setAvailableModels] = useState<Record<string, any>>({});
  const [modelParams, setModelParams] = useState<Record<string, any>>({});
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [availablePreprocessors, setAvailablePreprocessors] = useState<Record<string, any>>({});
  const [preprocessingSteps, setPreprocessingSteps] = useState<PreprocessingStepConfig[]>([]);
  const [isLoadingPreprocessors, setIsLoadingPreprocessors] = useState(false);
  const [newPreprocessorType, setNewPreprocessorType] = useState<string>("");
  const nextPreprocessingStepId = useRef(0);
  const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfigState>({
    heuristic_enabled: true,
    heuristic_window_size: 300,
    heuristic_min_samples: 30,
    heuristic_zscore_threshold: 3.0,
    sensor_key_strategy: "full_hierarchy",
    sensor_freshness_seconds: 30,
  });

  const [activeServices, setActiveServices] = useState<ActiveService[]>([]);
  const [isLoadingServices, setIsLoadingServices] = useState(false);

  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [isLoadingAnomalies, setIsLoadingAnomalies] = useState(false);

  useEffect(() => {
    if (!chargerId) return;

    loadAllTelemetryTypes(chargerId);
  }, [loadAllTelemetryTypes, chargerId]);

  useEffect(() => {
    if (!chargerId) return;
    setTopicPatternInput(`charger/${chargerId}/live-telemetry/#`);
  }, [chargerId]);

  const loadModels = useCallback(async () => {
    try {
      setIsLoadingModels(true);
      const response = await apiUtils.get<Record<string, any>>(API_CONFIG.ENDPOINTS.MONITORING.MODELS);
      setAvailableModels(response || {});
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to load models: ${errorMessage}`);
    } finally {
      setIsLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const loadPreprocessors = useCallback(async () => {
    try {
      setIsLoadingPreprocessors(true);
      const response = await apiUtils.get<Record<string, any>>(API_CONFIG.ENDPOINTS.MONITORING.PREPROCESSORS);
      setAvailablePreprocessors(response || {});
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to load preprocessors: ${errorMessage}`);
    } finally {
      setIsLoadingPreprocessors(false);
    }
  }, []);

  useEffect(() => {
    loadPreprocessors();
  }, [loadPreprocessors]);

  const applyModelDefaults = useCallback(
    (modelType: string) => {
      const modelInfo = availableModels[modelType];
      const properties = modelInfo?.parameters?.properties || {};
      const defaults: Record<string, any> = {};
      Object.entries(properties).forEach(([key, schema]: [string, any]) => {
        if (schema && typeof schema === "object" && schema.default !== undefined) {
          defaults[key] = schema.default;
        }
      });
      return defaults;
    },
    [availableModels]
  );

  const applyPreprocessorDefaults = useCallback(
    (preType: string) => {
      const info = availablePreprocessors[preType];
      const properties = info?.parameters?.properties || {};
      const defaults: Record<string, any> = {};
      Object.entries(properties).forEach(([key, schema]: [string, any]) => {
        if (schema && typeof schema === "object" && schema.default !== undefined) {
          defaults[key] = schema.default;
        }
      });
      return defaults;
    },
    [availablePreprocessors]
  );

  const handleModelSelect = useCallback(
    (modelType: string) => {
      setSelectedAlgorithm(modelType);
      setModelParams(applyModelDefaults(modelType));
    },
    [applyModelDefaults]
  );

  const handleParamChange = useCallback((key: string, rawValue: string, schemaType?: string) => {
    const parsed = parseNumericInput(rawValue, schemaType);
    setModelParams((prev) => ({ ...prev, [key]: parsed }));
  }, []);

  const handleAddPreprocessor = useCallback(() => {
    if (!newPreprocessorType) return;
    const defaults = applyPreprocessorDefaults(newPreprocessorType);
    const stepId = `pre-${nextPreprocessingStepId.current++}`;
    setPreprocessingSteps((prev) => [
      ...prev,
      { id: stepId, type: newPreprocessorType, params: defaults },
    ]);
    setNewPreprocessorType("");
  }, [applyPreprocessorDefaults, newPreprocessorType]);

  const handlePreprocessorParamChange = useCallback(
    (index: number, key: string, rawValue: string, schemaType?: string) => {
      const parsed = parseNumericInput(rawValue, schemaType);
      setPreprocessingSteps((prev) => {
        const updated = [...prev];
        updated[index] = {
          ...updated[index],
          params: { ...(updated[index].params || {}), [key]: parsed },
        };
        return updated;
      });
    },
    []
  );

  const handleRemovePreprocessor = useCallback((index: number) => {
    setPreprocessingSteps((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleMovePreprocessorUp = useCallback((index: number) => {
    if (index === 0) return;
    setPreprocessingSteps((prev) => {
      const updated = [...prev];
      [updated[index - 1], updated[index]] = [updated[index], updated[index - 1]];
      return updated;
    });
  }, []);

  const handleMovePreprocessorDown = useCallback((index: number) => {
    setPreprocessingSteps((prev) => {
      if (index >= prev.length - 1) return prev;
      const updated = [...prev];
      [updated[index], updated[index + 1]] = [updated[index + 1], updated[index]];
      return updated;
    });
  }, []);

  const handlePerformanceNumberChange = useCallback(
    (
      key:
        | "heuristic_window_size"
        | "heuristic_min_samples"
        | "heuristic_zscore_threshold"
        | "sensor_freshness_seconds",
      rawValue: string
    ) => {
      const parsed = parseFloat(rawValue);
      if (Number.isNaN(parsed)) {
        return;
      }
      setPerformanceConfig((prev) => ({
        ...prev,
        [key]:
          key === "heuristic_window_size" || key === "heuristic_min_samples"
            ? Math.max(1, Math.round(parsed))
            : parsed,
      }));
    },
    []
  );

  useEffect(() => {
    if (monitoringKeys.length === 0) return; // if no keys given do nothing
    if (Object.keys(visibleMap).length > 0) return; // if keys already initialised also do nothing
    setVisibleMap(Object.fromEntries(monitoringKeys.map((k) => [k, false]))); //k = keys, bool = should all be shown per default or not
  }, [monitoringKeys, visibleMap]);

  // Load active services with Docker status
  const loadActiveServices = useCallback(async () => {
    try {
      setIsLoadingServices(true);
      // Include Docker status to get actual container state
      const response = await apiUtils.get(
        `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?include_docker_status=true`
      );
      setActiveServices(response || []);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to load active services: ${errorMessage}`);
    } finally {
      setIsLoadingServices(false);
    }
  }, []);

  // Load anomalies for current charger
  const loadAnomalies = useCallback(async () => {
    if (!chargerId) return;

    try {
      setIsLoadingAnomalies(true);
      const response = await apiUtils.get<Anomaly[]>(
        API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId)
      );
      setAnomalies(response || []);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to load anomalies: ${errorMessage}`);
    } finally {
      setIsLoadingAnomalies(false);
    }
  }, [chargerId]);

  // Delete service
  const deleteService = useCallback(async (containerName: string) => {
    if (!confirm(`Are you sure you want to delete the service "${containerName}"?`)) {
      return;
    }

    try {
      await apiUtils.delete(`${API_CONFIG.ENDPOINTS.MONITORING.STOP}?container_name=${encodeURIComponent(containerName)}`);
      toast.success(`Service "${containerName}" deleted successfully`);
      // Refresh the services list
      await loadActiveServices();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to delete service: ${errorMessage}`);
    }
  }, [loadActiveServices]);

  // Load services on component mount and set up refresh interval
  useEffect(() => {
    loadActiveServices();

    // Refresh services every 30 seconds
    const interval = setInterval(loadActiveServices, 30000);

    return () => clearInterval(interval);
  }, [loadActiveServices]);

  // Load anomalies on component mount and set up refresh interval
  useEffect(() => {
    loadAnomalies();

    // Refresh anomalies every 30 seconds
    const anomalyInterval = setInterval(loadAnomalies, 30000);

    return () => clearInterval(anomalyInterval);
  }, [loadAnomalies]);

  const submitAnomalyDetection = async () => {
    if (!selectedAlgorithm || !chargerId) {
      alert("Please select an algorithm.");
      return;
    }

    try {
      const mqttTopics =
        topicMode === "selected_sensors"
          ? activeKeys.map((sensorType) => `charger/${chargerId}/live-telemetry/${sensorType}`)
          : parseTopicPatterns(topicPatternInput);

      if (mqttTopics.length === 0) {
        alert("Please select at least one sensor or provide at least one topic pattern.");
        return;
      }

      if (performanceConfig.heuristic_min_samples > performanceConfig.heuristic_window_size) {
        alert("Heuristic min samples must be less than or equal to window size.");
        return;
      }

      // Generate unique container name
      const containerName = `radar-${chargerId}-${Date.now()}`;

      // Clean params (drop empty strings)
      const cleanedParams = Object.fromEntries(
        Object.entries(modelParams || {}).filter(([, value]) => value !== "" && value !== undefined)
      );

      await apiUtils.post(
        API_CONFIG.ENDPOINTS.MONITORING.START,
        {
          container_name: containerName,
          service_type: "radar",
          mqtt_topics: mqttTopics,
          model_type: selectedAlgorithm,
          model_params: cleanedParams,
          preprocessing_steps: preprocessingSteps.map((step) => ({
            type: step.type,
            params: Object.fromEntries(
              Object.entries(step.params || {}).filter(([, value]) => value !== "" && value !== undefined)
            ),
          })),
          performance_config: {
            heuristic_enabled: performanceConfig.heuristic_enabled,
            heuristic_window_size: performanceConfig.heuristic_window_size,
            heuristic_min_samples: performanceConfig.heuristic_min_samples,
            heuristic_zscore_threshold: performanceConfig.heuristic_zscore_threshold,
            sensor_key_strategy: performanceConfig.sensor_key_strategy,
            sensor_freshness_seconds: performanceConfig.sensor_freshness_seconds,
          },
        }
      );

      toast.success(`Monitoring service started successfully! Container: ${containerName}`);
      // Refresh the services list
      await loadActiveServices();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Error: ${errorMessage}`);
    }
  };

  return (
    <>
      <NavigationBar />
      <div className="flex mt-5">
        <Card className="ml-16 bg-white shadow-md w-11/12 min-h-11/12 dark:bg-neutral-950">
          <div>
            <CardTitle className="ml-5">
              Monitoring for the Charger {chargerId}
            </CardTitle>
            <CardContent>
              <div className="flex items-start gap-6">
                {/* Left Side */}
                <div className="flex flex-col w-2/5">
                  <label className="text-sm font-semibold mt-4 mb-2">Topic Input Mode</label>
                  <select
                    className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                    value={topicMode}
                    onChange={(e) => setTopicMode(e.target.value as "selected_sensors" | "direct_patterns")}
                  >
                    <option value="selected_sensors">Build from selected sensors</option>
                    <option value="direct_patterns">Use direct topic patterns</option>
                  </select>

                  {topicMode === "selected_sensors" ? (
                    <>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button className="w-30 mb-5 mr-3 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer">
                            Sensor types
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w100">
                          <DropdownMenuLabel>Sensors</DropdownMenuLabel>
                          <DropdownMenuSeparator />
                          {monitoringKeys.map((key) => (
                            <DropdownMenuCheckboxItem
                              key={key}
                              checked={visibleMap[key]}
                              onCheckedChange={() =>
                                setVisibleMap((prev) => ({
                                  ...prev,
                                  [key]: !prev[key],
                                }))
                              }
                              onClick={(e) => e.stopPropagation()}
                            >
                              {key}
                            </DropdownMenuCheckboxItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>

                      <div className="mt-6">
                        <h2 className="text-lg font-bold mb-2">
                          Picked values for the Anomaly Detection:
                        </h2>
                        <ul className="list-disc list-inside space-y-1">
                          {activeKeys.map((key) => (
                            <li key={key} className="ml-2">
                              {key}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </>
                  ) : (
                    <div className="mt-4 space-y-3">
                      <label className="text-sm font-semibold">Topic Patterns</label>
                      <textarea
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white min-h-36"
                        value={topicPatternInput}
                        onChange={(e) => setTopicPatternInput(e.target.value)}
                        placeholder="One topic per line or comma-separated. Supports MQTT wildcards + and #."
                      />
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setTopicPatternInput("#")}
                        >
                          Use all topics (#)
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setTopicPatternInput(`charger/${chargerId}/live-telemetry/#`)}
                        >
                          Charger wildcard
                        </Button>
                      </div>
                      <p className="text-xs text-gray-500">
                        Parsed topics: {parseTopicPatterns(topicPatternInput).join(", ") || "none"}
                      </p>
                    </div>
                  )}

                  <div className="mt-6">
                    <h2 className="text-lg font-bold mb-2">
                      Effective Topics:
                    </h2>
                    <ul className="list-disc list-inside space-y-1">
                      {(topicMode === "selected_sensors"
                        ? activeKeys.map((sensorType) => `charger/${chargerId}/live-telemetry/${sensorType}`)
                        : parseTopicPatterns(topicPatternInput)
                      ).map((topic) => (
                        <li key={topic} className="ml-2">
                          {topic}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="h-80 border-l border-gray-300 ml-4 mr-4"></div>
                <div className="flex flex-col w-2/5">
                  <label className="text-sm font-semibold mt-4 mb-2">Algorithm</label>
                  <select
                    className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                    value={selectedAlgorithm || ""}
                    onChange={(e) => handleModelSelect(e.target.value)}
                    disabled={isLoadingModels}
                  >
                    <option value="" disabled>
                      {isLoadingModels ? "Loading models..." : "Select algorithm"}
                    </option>
                    {Object.keys(availableModels).map((key) => (
                      <option key={key} value={key}>
                        {key}
                      </option>
                    ))}
                  </select>

                  <div className="mt-10">
                    <h2 className="text-lg font-bold mb-2">
                      Picked Algorithm:
                    </h2>
                    <p>{selectedAlgorithm || "None selected"}</p>
                  </div>

                  {selectedAlgorithm && (
                    <div className="mt-6 space-y-3">
                      <h3 className="text-md font-semibold">Parameters</h3>
                      {Object.entries(availableModels[selectedAlgorithm]?.parameters?.properties || {}).length === 0 && (
                        <p className="text-sm text-gray-500">No parameters for this model.</p>
                      )}
                      {Object.entries(availableModels[selectedAlgorithm]?.parameters?.properties || {}).map(
                        ([key, schema]: [string, any]) => (
                          <div key={key} className="flex flex-col">
                            <label className="text-sm font-medium mb-1">
                              {key}
                              {schema?.description ? (
                                <span className="text-xs text-gray-500 ml-1">({schema.description})</span>
                              ) : null}
                            </label>
                            <input
                              type={schema?.type === "integer" || schema?.type === "number" ? "number" : "text"}
                              className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                              value={modelParams[key] ?? ""}
                              onChange={(e) => handleParamChange(key, e.target.value, schema?.type)}
                              min={schema?.minimum}
                              max={schema?.maximum}
                              step="any"
                            />
                          </div>
                        )
                      )}
                    </div>
                  )}

                  <div className="mt-8 space-y-3">
                    <h3 className="text-md font-semibold">Detection Heuristics</h3>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={performanceConfig.heuristic_enabled}
                        onChange={(event) =>
                          setPerformanceConfig((prev) => ({
                            ...prev,
                            heuristic_enabled: event.target.checked,
                          }))
                        }
                      />
                      Enable moving-window z-score trigger
                    </label>
                    <div className="flex flex-col">
                      <label className="text-sm font-medium mb-1">Window Size</label>
                      <input
                        type="number"
                        min={3}
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                        value={performanceConfig.heuristic_window_size}
                        onChange={(event) =>
                          handlePerformanceNumberChange(
                            "heuristic_window_size",
                            event.target.value
                          )
                        }
                      />
                    </div>
                    <div className="flex flex-col">
                      <label className="text-sm font-medium mb-1">Min Samples</label>
                      <input
                        type="number"
                        min={2}
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                        value={performanceConfig.heuristic_min_samples}
                        onChange={(event) =>
                          handlePerformanceNumberChange(
                            "heuristic_min_samples",
                            event.target.value
                          )
                        }
                      />
                    </div>
                    <div className="flex flex-col">
                      <label className="text-sm font-medium mb-1">Z-Score Threshold</label>
                      <input
                        type="number"
                        min={0.1}
                        step="0.1"
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                        value={performanceConfig.heuristic_zscore_threshold}
                        onChange={(event) =>
                          handlePerformanceNumberChange(
                            "heuristic_zscore_threshold",
                            event.target.value
                          )
                        }
                      />
                    </div>
                    <div className="flex flex-col">
                      <label className="text-sm font-medium mb-1">Sensor Strategy</label>
                      <select
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                        value={performanceConfig.sensor_key_strategy}
                        onChange={(event) =>
                          setPerformanceConfig((prev) => ({
                            ...prev,
                            sensor_key_strategy: event.target.value as SensorKeyStrategy,
                          }))
                        }
                      >
                        <option value="full_hierarchy">full_hierarchy</option>
                        <option value="top_level">top_level</option>
                        <option value="leaf">leaf</option>
                      </select>
                    </div>
                    <div className="flex flex-col">
                      <label className="text-sm font-medium mb-1">Sensor Freshness (s)</label>
                      <input
                        type="number"
                        min={1}
                        step="1"
                        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                        value={performanceConfig.sensor_freshness_seconds}
                        onChange={(event) =>
                          handlePerformanceNumberChange(
                            "sensor_freshness_seconds",
                            event.target.value
                          )
                        }
                      />
                    </div>
                  </div>

                  <PreprocessingSection
                    steps={preprocessingSteps}
                    availablePreprocessors={availablePreprocessors}
                    newPreprocessorType={newPreprocessorType}
                    isLoading={isLoadingPreprocessors}
                    onSelectType={setNewPreprocessorType}
                    onAdd={handleAddPreprocessor}
                    onParamChange={handlePreprocessorParamChange}
                    onMoveUp={handleMovePreprocessorUp}
                    onMoveDown={handleMovePreprocessorDown}
                    onRemove={handleRemovePreprocessor}
                  />
                </div>
              </div>
              <Button
                className="w-30 mt-4 bg-indigo-800 hover:bg-indigo-700 cursor-pointer"
                onClick={submitAnomalyDetection}
              >
                Send
              </Button>
            </CardContent>
          </div>
        </Card>
      </div>

      <ActiveServicesSection
        services={activeServices}
        isLoading={isLoadingServices}
        chargerId={chargerId}
        onDelete={deleteService}
      />

      <AnomaliesSection
        anomalies={anomalies}
        isLoading={isLoadingAnomalies}
        chargerId={chargerId}
        onRefresh={loadAnomalies}
      />
    </>
  );
};

export default Monitoring;
