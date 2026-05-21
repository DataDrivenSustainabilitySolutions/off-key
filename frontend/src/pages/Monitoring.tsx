import { NavigationBar } from "@/components/NavigationBar";
import { useParams } from "react-router-dom";
import { useFetch } from "@/dataFetch/UseFetch";
import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
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
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  Layers3,
  RadioTower,
  RefreshCw,
  Send,
  Settings2,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getStatusDisplay } from "@/types/monitoring";
import {
  formatAnomalyValue,
  getAnomalyValueClassName,
  getAnomalyValueLabel,
  isProbabilityAnomalyValue,
} from "@/lib/anomaly-semantics";
import { formatAnomalySensorSet } from "@/lib/anomaly-utils";
import type { Anomaly } from "@/types/charger";
import type {
  ActiveService,
  FdrControlMethod,
  ModelDefinition,
  ModelParams,
  ParameterSchema,
  PreprocessingStepConfig,
  PreprocessorDefinition,
} from "@/types/monitoring";

type ConfigValue = string | number | boolean;
type ConfigInputValue = string | boolean;

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

const parseConfigInput = (
  rawValue: ConfigInputValue,
  schemaType?: string
): ConfigValue => {
  if (typeof rawValue === "boolean") {
    return rawValue;
  }

  return parseNumericInput(rawValue, schemaType);
};

const isConfigValue = (value: unknown): value is ConfigValue =>
  typeof value === "string" ||
  typeof value === "number" ||
  typeof value === "boolean";

const getInputType = (schemaType?: string): "checkbox" | "number" | "text" => {
  if (schemaType === "boolean") {
    return "checkbox";
  }
  if (schemaType === "integer" || schemaType === "number") {
    return "number";
  }
  return "text";
};

const getTextInputValue = (
  value: string | number | boolean | undefined
): string | number => {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return value ?? "";
};

const parseTopicPatterns = (raw: string): string[] => {
  return raw
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
};

type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";
type AlignmentMode = "strict_barrier";
type MonitoringStrategy = "static_baseline" | "adaptive_stream";

type PerformanceConfigState = {
  heuristic_enabled: boolean;
  heuristic_window_size: number;
  heuristic_min_samples: number;
  heuristic_tail_alpha: number;
  alignment_mode: AlignmentMode;
  sensor_key_strategy: SensorKeyStrategy;
  sensor_freshness_seconds: number;
};

type StaticBaselineConfigState = {
  model_type: string;
  model_params: ModelParams;
  training_window_size: number;
  calibration_fraction: number;
  fdr_method: FdrControlMethod;
  fdr_alpha: number;
  fdr_wealth: number;
  fdr_lambda: number;
  fdr_cutoff: number;
};

const DEFAULT_MODEL_TYPE = "knn";
const DEFAULT_STATIC_MODEL_TYPE = "pyod_iforest";
const DEFAULT_MODEL_PARAMS: ModelParams = {
  k: 5,
  window_size: 2500,
  warm_up: 500,
};
const DEFAULT_STATIC_MODEL_PARAMS: ModelParams = {
  n_estimators: 100,
  contamination: 0.1,
  random_state: 42,
};
const DEFAULT_PREPROCESSING_STEPS: PreprocessingStepConfig[] = [
  {
    id: "pre-0",
    type: "standard_scaler",
    params: { with_std: true },
  },
];

const FORM_CONTROL_CLASS =
  "h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50";
const PRIMARY_ACTION_BUTTON_CLASS = "";
const FIELD_LABEL_CLASS = "text-sm font-medium text-foreground";
const FIELD_HELP_CLASS = "mt-1 text-xs leading-5 text-muted-foreground";
const PANEL_SECTION_CLASS =
  "min-w-0 space-y-4 border-t border-border/70 pt-5 first:border-t-0 first:pt-0";
const CHIP_CLASS =
  "inline-flex max-w-full items-center rounded-full border border-border/70 bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-xs";
const QUIET_SURFACE_CLASS =
  "rounded-md border border-border/70 bg-muted/20 p-4";

const formatStrategyLabel = (strategy?: MonitoringStrategy): string => {
  if (strategy === "static_baseline") return "Static";
  if (strategy === "adaptive_stream") return "Dynamic";
  return "Unknown";
};

const getStrategyBadgeClassName = (strategy?: MonitoringStrategy): string =>
  strategy === "static_baseline"
    ? "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/25 dark:text-sky-200"
    : strategy === "adaptive_stream"
    ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200"
    : "border-border bg-muted text-muted-foreground";

const formatDateTime = (value?: string): string =>
  value ? new Date(value).toLocaleString() : "Unknown";

const extractChargerIdFromContainer = (containerName: string): string => {
  const match = containerName.match(/^radar-(.+)-\d+$/);
  return match ? match[1] : "Unknown";
};

const MonitoringSectionCard: React.FC<{
  title: React.ReactNode;
  children: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  contentClassName?: string;
}> = ({ title, children, description, actions, className, contentClassName }) => (
  <SectionPanel
    title={title}
    description={description}
    actions={actions}
    className={className}
    contentClassName={contentClassName}
  >
    {children}
  </SectionPanel>
);

const StatusPill: React.FC<{ label: string; className?: string }> = ({
  label,
  className,
}) => (
  <span
    className={cn(
      "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
      className
    )}
  >
    {label}
  </span>
);

const StrategyPill: React.FC<{ strategy?: MonitoringStrategy }> = ({
  strategy,
}) => (
  <span
    className={cn(
      "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
      getStrategyBadgeClassName(strategy)
    )}
  >
    {formatStrategyLabel(strategy)}
  </span>
);

const EmptyState: React.FC<{
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}> = ({ icon: Icon, title, description }) => (
  <div className="flex min-h-40 flex-col items-center justify-center px-4 py-10 text-center">
    <div className="mb-3 flex size-10 items-center justify-center rounded-md border bg-muted/30 text-muted-foreground">
      <Icon className="h-5 w-5" />
    </div>
    <div className="text-sm font-medium">{title}</div>
    <div className="mt-1 max-w-md text-sm text-muted-foreground">
      {description}
    </div>
  </div>
);

const SectionEyebrow: React.FC<{
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
}> = ({ icon: Icon, title, description }) => (
  <div className="flex items-start gap-3">
    <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-background text-muted-foreground">
      <Icon className="h-4 w-4" />
    </div>
    <div className="min-w-0">
      <h3 className="text-sm font-semibold leading-5">{title}</h3>
      {description ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
  </div>
);

const PreprocessingSection: React.FC<{
  steps: PreprocessingStepConfig[];
  availablePreprocessors: Record<string, PreprocessorDefinition>;
  newPreprocessorType: string;
  isLoading: boolean;
  onSelectType: (type: string) => void;
  onAdd: () => void;
  onParamChange: (index: number, key: string, rawValue: ConfigInputValue, schemaType?: string) => void;
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
  <div className={PANEL_SECTION_CLASS}>
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <SectionEyebrow
        icon={Layers3}
        title="Preprocessing"
        description="Optional transforms before model scoring."
      />
      {isLoading ? (
        <span className="text-xs text-muted-foreground">Loading...</span>
      ) : null}
    </div>
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
      <select
        className={FORM_CONTROL_CLASS}
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
        className={PRIMARY_ACTION_BUTTON_CLASS}
        disabled={!newPreprocessorType || isLoading}
        onClick={onAdd}
      >
        <Layers3 className="h-4 w-4" />
        Add
      </Button>
    </div>

    {steps.length === 0 && (
      <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        No preprocessing steps selected.
      </p>
    )}

    <div className="space-y-3">
      {steps.map((step, index) => {
        const schemaProps: Record<string, ParameterSchema> =
          availablePreprocessors[step.type]?.parameters?.properties || {};
        return (
          <div key={step.id} className="min-w-0 rounded-md border bg-background p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold text-muted-foreground">
                  {index + 1}
                </span>
                <div className="truncate text-sm font-semibold">{step.type}</div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => onMoveUp(index)}
                  disabled={index === 0}
                  aria-label="Move preprocessing step up"
                >
                  <ChevronUp className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => onMoveDown(index)}
                  disabled={index === steps.length - 1}
                  aria-label="Move preprocessing step down"
                >
                  <ChevronDown className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive"
                  onClick={() => onRemove(index)}
                  aria-label="Remove preprocessing step"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {Object.entries(schemaProps).length === 0 && (
                <p className="text-sm text-muted-foreground">No parameters.</p>
              )}
              {Object.entries(schemaProps).map(([key, schema]) => (
                <div key={key} className="flex flex-col">
                  <label className="mb-1 text-sm font-medium">
                    {key}
                    {schema?.description ? (
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({schema.description})
                      </span>
                    ) : null}
                  </label>
                  <input
                    type={getInputType(schema?.type)}
                    className={FORM_CONTROL_CLASS}
                    checked={
                      schema?.type === "boolean"
                        ? Boolean(step.params?.[key])
                        : undefined
                    }
                    value={
                      schema?.type === "boolean"
                        ? undefined
                        : getTextInputValue(step.params?.[key])
                    }
                    onChange={(e) =>
                      onParamChange(
                        index,
                        key,
                        schema?.type === "boolean" ? e.target.checked : e.target.value,
                        schema?.type
                      )
                    }
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
  const chargerSpecificServices = React.useMemo(() => {
    if (!chargerId) return services;
    return services.filter((service) => extractChargerIdFromContainer(service.container_name) === chargerId);
  }, [services, chargerId]);

  return (
    <MonitoringSectionCard
      title="Active Services"
      description={`${chargerSpecificServices.length} services for charger ${chargerId}`}
      contentClassName="p-0"
    >
      {isLoading ? (
        <EmptyState
          icon={RefreshCw}
          title="Loading active services"
          description="The service list is refreshing from the backend."
        />
      ) : chargerSpecificServices.length === 0 ? (
        <EmptyState
          icon={RadioTower}
          title="No active services"
          description={`Start a monitoring workload to track charger ${chargerId}.`}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40">
              <TableHead>Service</TableHead>
              <TableHead>Strategy</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Topics</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {chargerSpecificServices.map((service) => {
              const statusDisplay = getStatusDisplay(
                service.docker_status,
                service.status
              );
              return (
                <TableRow key={service.id} className="align-top">
                  <TableCell>
                    <div className="max-w-[18rem] truncate font-medium">
                      {service.container_name}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {extractChargerIdFromContainer(service.container_name)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StrategyPill strategy={service.monitoring_strategy} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {service.model_type || "Unknown"}
                  </TableCell>
                  <TableCell>
                    <div
                      className="max-w-xs truncate text-sm"
                      title={service.mqtt_topics.join(", ")}
                    >
                      {service.mqtt_topics.length > 0
                        ? service.mqtt_topics.slice(0, 2).join(", ") +
                          (service.mqtt_topics.length > 2
                            ? ` +${service.mqtt_topics.length - 2} more`
                            : "")
                        : "No topics"}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusPill
                      label={statusDisplay.label}
                      className={statusDisplay.className}
                    />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDateTime(service.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive hover:text-destructive"
                      onClick={() => onDelete(service.container_name)}
                      aria-label="Stop monitoring service"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </MonitoringSectionCard>
  );
};

const AnomaliesSection: React.FC<{
  anomalies: Anomaly[];
  isLoading: boolean;
  chargerId?: string;
  onRefresh: () => void;
}> = ({ anomalies, isLoading, chargerId, onRefresh }) => (
  <MonitoringSectionCard
    title="Detected Anomalies"
    description={`${anomalies.length} anomalies for charger ${chargerId}`}
    actions={
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={isLoading}>
        <RefreshCw className={isLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        {isLoading ? "Refreshing..." : "Refresh"}
      </Button>
    }
    contentClassName="p-0"
  >
    {isLoading ? (
      <EmptyState
        icon={RefreshCw}
        title="Loading anomalies"
        description="Recent detections are being refreshed."
      />
    ) : anomalies.length === 0 ? (
      <EmptyState
        icon={CheckCircle2}
        title="No anomalies detected"
        description={`No recent detections are loaded for charger ${chargerId}.`}
      />
    ) : (
      <div className="max-h-96 overflow-y-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow className="bg-muted/40 hover:bg-muted/40">
              <TableHead>Timestamp</TableHead>
              <TableHead>Telemetry</TableHead>
              <TableHead>Sensors</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>p-value</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {anomalies.slice(0, 50).map((anomaly, index) => (
              <TableRow key={`${anomaly.timestamp}-${index}`}>
                <TableCell className="font-medium">
                  {new Date(anomaly.timestamp).toLocaleString()}
                </TableCell>
                <TableCell>
                  <StatusPill
                    label={
                      anomaly.telemetry_type === "__multivariate__"
                        ? "multivariate"
                        : anomaly.telemetry_type
                    }
                    className="bg-sky-100 text-sky-800 dark:bg-sky-900/35 dark:text-sky-200"
                  />
                </TableCell>
                <TableCell
                  className="max-w-56 truncate text-xs text-muted-foreground"
                  title={formatAnomalySensorSet(anomaly.sensor_set)}
                >
                  {formatAnomalySensorSet(anomaly.sensor_set)}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {anomaly.anomaly_type}
                </TableCell>
                <TableCell>
                  {isProbabilityAnomalyValue(anomaly.value_type) ? (
                    <StatusPill
                      label={formatAnomalyValue(
                        anomaly.anomaly_value,
                        anomaly.value_type
                      )}
                      className={getAnomalyValueClassName(
                        anomaly.anomaly_value,
                        anomaly.value_type
                      )}
                    />
                  ) : (
                    <StatusPill
                      label={`${formatAnomalyValue(
                        anomaly.anomaly_value,
                        anomaly.value_type
                      )} legacy`}
                      className="bg-muted text-muted-foreground"
                    />
                  )}
                  <span className="sr-only">
                    {getAnomalyValueLabel(anomaly.value_type)}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {anomalies.length > 50 && (
          <div className="border-t py-3 text-center text-sm text-muted-foreground">
            Showing 50 of {anomalies.length} anomalies
          </div>
        )}
      </div>
    )}
  </MonitoringSectionCard>
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
        .filter(([, visible]) => visible)
        .map(([key]) => key),
    [visibleMap]
  );
  const [topicMode, setTopicMode] = useState<"selected_sensors" | "direct_patterns">(
    "selected_sensors"
  );
  const [topicPatternInput, setTopicPatternInput] = useState<string>("");
  const [monitoringStrategy, setMonitoringStrategy] = useState<MonitoringStrategy>(
    "static_baseline"
  );
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<string | null>(
    DEFAULT_MODEL_TYPE
  );
  const [availableModels, setAvailableModels] = useState<Record<string, ModelDefinition>>({});
  const [modelParams, setModelParams] = useState<ModelParams>(
    DEFAULT_MODEL_PARAMS
  );
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [availablePreprocessors, setAvailablePreprocessors] = useState<Record<string, PreprocessorDefinition>>({});
  const [preprocessingSteps, setPreprocessingSteps] = useState<PreprocessingStepConfig[]>(
    DEFAULT_PREPROCESSING_STEPS
  );
  const [isLoadingPreprocessors, setIsLoadingPreprocessors] = useState(false);
  const [newPreprocessorType, setNewPreprocessorType] = useState<string>("");
  const nextPreprocessingStepId = useRef(DEFAULT_PREPROCESSING_STEPS.length);
  const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfigState>({
    heuristic_enabled: true,
    heuristic_window_size: 1000,
    heuristic_min_samples: 300,
    heuristic_tail_alpha: 0.005,
    alignment_mode: "strict_barrier",
    sensor_key_strategy: "full_hierarchy",
    sensor_freshness_seconds: 30,
  });
  const [staticBaselineConfig, setStaticBaselineConfig] =
    useState<StaticBaselineConfigState>({
      model_type: DEFAULT_STATIC_MODEL_TYPE,
      model_params: DEFAULT_STATIC_MODEL_PARAMS,
      training_window_size: 1200,
      calibration_fraction: 0.3,
      fdr_method: "saffron",
      fdr_alpha: 0.05,
      fdr_wealth: 0.025,
      fdr_lambda: 0.5,
      fdr_cutoff: 0.05,
    });
  const [showStaticAdvanced, setShowStaticAdvanced] = useState(false);
  const [showDynamicAdvanced, setShowDynamicAdvanced] = useState(false);

  const [activeServices, setActiveServices] = useState<ActiveService[]>([]);
  const [isLoadingServices, setIsLoadingServices] = useState(false);

  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [isLoadingAnomalies, setIsLoadingAnomalies] = useState(false);

  const effectiveTopics = useMemo(
    () =>
      topicMode === "selected_sensors"
        ? activeKeys.map((sensorType) => `charger/${chargerId}/live-telemetry/${sensorType}`)
        : parseTopicPatterns(topicPatternInput),
    [activeKeys, chargerId, topicMode, topicPatternInput]
  );

  const chargerServiceCount = useMemo(() => {
    if (!chargerId) return activeServices.length;
    return activeServices.filter(
      (service) => extractChargerIdFromContainer(service.container_name) === chargerId
    ).length;
  }, [activeServices, chargerId]);

  const staticModels = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(availableModels).filter(
          ([key, model]) =>
            model.strategy === "static_baseline" || key.startsWith("pyod_")
        )
      ),
    [availableModels]
  );

  const adaptiveModels = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(availableModels).filter(
          ([key, model]) =>
            model.strategy !== "static_baseline" && !key.startsWith("pyod_")
        )
      ),
    [availableModels]
  );

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
      const response = await apiUtils.get<Record<string, ModelDefinition>>(API_CONFIG.ENDPOINTS.MONITORING.MODELS);
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
      const response = await apiUtils.get<Record<string, PreprocessorDefinition>>(API_CONFIG.ENDPOINTS.MONITORING.PREPROCESSORS);
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
      const defaults: ModelParams = {};
      Object.entries(modelInfo?.default_parameters || {}).forEach(([key, value]) => {
        if (isConfigValue(value)) {
          defaults[key] = value;
        }
      });
      Object.entries(properties).forEach(([key, schema]) => {
        if (
          defaults[key] === undefined &&
          schema.default !== undefined &&
          isConfigValue(schema.default)
        ) {
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
      const defaults: Record<string, ConfigValue> = {};
      Object.entries(properties).forEach(([key, schema]) => {
        if (schema.default !== undefined && isConfigValue(schema.default)) {
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
      const defaults = applyModelDefaults(modelType);
      if (modelType === DEFAULT_MODEL_TYPE) {
        setModelParams({ ...defaults, ...DEFAULT_MODEL_PARAMS });
        return;
      }
      setModelParams(defaults);
    },
    [applyModelDefaults]
  );

  const handleStaticModelSelect = useCallback(
    (modelType: string) => {
      const defaults = applyModelDefaults(modelType);
      setStaticBaselineConfig((prev) => ({
        ...prev,
        model_type: modelType,
        model_params:
          modelType === DEFAULT_STATIC_MODEL_TYPE
            ? { ...defaults, ...DEFAULT_STATIC_MODEL_PARAMS }
            : defaults,
      }));
    },
    [applyModelDefaults]
  );

  const handleParamChange = useCallback((key: string, rawValue: ConfigInputValue, schemaType?: string) => {
    const parsed = parseConfigInput(rawValue, schemaType);
    setModelParams((prev) => ({ ...prev, [key]: parsed }));
  }, []);

  const handleStaticParamChange = useCallback((key: string, rawValue: ConfigInputValue, schemaType?: string) => {
    const parsed = parseConfigInput(rawValue, schemaType);
    setStaticBaselineConfig((prev) => ({
      ...prev,
      model_params: { ...prev.model_params, [key]: parsed },
    }));
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
    (index: number, key: string, rawValue: ConfigInputValue, schemaType?: string) => {
      const parsed = parseConfigInput(rawValue, schemaType);
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
        | "heuristic_tail_alpha"
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
            : key === "sensor_freshness_seconds"
            ? Math.max(1, parsed)
            : key === "heuristic_tail_alpha"
            ? Math.min(Math.max(0.0001, parsed), 0.9999)
            : parsed,
      }));
    },
    []
  );

  const handleStaticNumberChange = useCallback(
    (
      key:
        | "training_window_size"
        | "calibration_fraction"
        | "fdr_alpha"
        | "fdr_wealth"
        | "fdr_lambda"
        | "fdr_cutoff",
      rawValue: string
    ) => {
      const parsed = parseFloat(rawValue);
      if (Number.isNaN(parsed)) {
        return;
      }
      setStaticBaselineConfig((prev) => ({
        ...prev,
        [key]:
          key === "training_window_size"
            ? Math.max(20, Math.round(parsed))
            : key === "calibration_fraction"
            ? Math.min(Math.max(0.01, parsed), 0.94)
            : Math.min(Math.max(0.0001, parsed), 0.9999),
      }));
    },
    []
  );

  useEffect(() => {
    const staticKeys = Object.keys(staticModels);
    if (staticKeys.length === 0) return;
    if (staticBaselineConfig.model_type in staticModels) return;
    handleStaticModelSelect(
      staticKeys.includes(DEFAULT_STATIC_MODEL_TYPE)
        ? DEFAULT_STATIC_MODEL_TYPE
        : staticKeys[0]
    );
  }, [handleStaticModelSelect, staticBaselineConfig.model_type, staticModels]);

  useEffect(() => {
    const adaptiveKeys = Object.keys(adaptiveModels);
    if (adaptiveKeys.length === 0) return;
    if (selectedAlgorithm && selectedAlgorithm in adaptiveModels) return;
    handleModelSelect(
      adaptiveKeys.includes(DEFAULT_MODEL_TYPE) ? DEFAULT_MODEL_TYPE : adaptiveKeys[0]
    );
  }, [adaptiveModels, handleModelSelect, selectedAlgorithm]);

  useEffect(() => {
    setVisibleMap((previous) => {
      const next = Object.fromEntries(
        monitoringKeys.map((key) => [key, previous[key] ?? true])
      );
      const previousKeys = Object.keys(previous);
      const nextKeys = Object.keys(next);
      const isUnchanged =
        previousKeys.length === nextKeys.length &&
        nextKeys.every((key) => previous[key] === next[key]);

      return isUnchanged ? previous : next;
    });
  }, [monitoringKeys]);

  // Load active services with Docker status
  const loadActiveServices = useCallback(async () => {
    try {
      setIsLoadingServices(true);
      // Include Docker status to get actual container state
      const response = await apiUtils.get<ActiveService[]>(
        `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?active_only=true&include_docker_status=true`
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

  // Stop service
  const deleteService = useCallback(async (containerName: string) => {
    if (!confirm(`Stop monitoring service "${containerName}"?`)) {
      return;
    }

    try {
      await apiUtils.delete(`${API_CONFIG.ENDPOINTS.MONITORING.STOP}?container_name=${encodeURIComponent(containerName)}`);
      toast.success(`Service "${containerName}" stopped successfully`);
      // Refresh the services list
      await loadActiveServices();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to stop service: ${errorMessage}`);
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
    const selectedModelType =
      monitoringStrategy === "static_baseline"
        ? staticBaselineConfig.model_type
        : selectedAlgorithm;

    if (!selectedModelType || !chargerId) {
      alert("Please select an algorithm.");
      return;
    }

    try {
      const mqttTopics = effectiveTopics;

      if (mqttTopics.length === 0) {
        alert("Please select at least one sensor or provide at least one topic pattern.");
        return;
      }

      if (performanceConfig.heuristic_min_samples > performanceConfig.heuristic_window_size) {
        alert("Heuristic min samples must be less than or equal to window size.");
        return;
      }

      if (
        monitoringStrategy === "static_baseline" &&
        staticBaselineConfig.fdr_method === "saffron" &&
        staticBaselineConfig.fdr_wealth >= staticBaselineConfig.fdr_alpha
      ) {
        alert("SAFFRON wealth must be less than alpha.");
        return;
      }

      // Generate unique container name
      const containerName = `radar-${chargerId}-${Date.now()}`;

      // Clean params (drop empty strings)
      const activeModelParams =
        monitoringStrategy === "static_baseline"
          ? staticBaselineConfig.model_params
          : modelParams;
      const cleanedParams = Object.fromEntries(
        Object.entries(activeModelParams || {}).filter(([, value]) => value !== "" && value !== undefined)
      );

      const cleanedPreprocessingSteps =
        monitoringStrategy === "adaptive_stream"
          ? preprocessingSteps.map((step) => ({
              type: step.type,
              params: Object.fromEntries(
                Object.entries(step.params || {}).filter(([, value]) => value !== "" && value !== undefined)
              ),
            }))
          : [];

      const commonPerformanceConfig = {
        alignment_mode: performanceConfig.alignment_mode,
        sensor_key_strategy: performanceConfig.sensor_key_strategy,
        sensor_freshness_seconds: performanceConfig.sensor_freshness_seconds,
      };

      const adaptivePerformanceConfig = {
        ...commonPerformanceConfig,
        heuristic_enabled: performanceConfig.heuristic_enabled,
        heuristic_window_size: performanceConfig.heuristic_window_size,
        heuristic_min_samples: performanceConfig.heuristic_min_samples,
        heuristic_tail_alpha: performanceConfig.heuristic_tail_alpha,
      };

      await apiUtils.post(
        API_CONFIG.ENDPOINTS.MONITORING.START,
        {
          container_name: containerName,
          service_type: "radar",
          mqtt_topics: mqttTopics,
          strategy: monitoringStrategy,
          model_type: selectedModelType,
          model_params: cleanedParams,
          preprocessing_steps: cleanedPreprocessingSteps,
          performance_config:
            monitoringStrategy === "adaptive_stream"
              ? adaptivePerformanceConfig
              : commonPerformanceConfig,
          static_baseline_config:
            monitoringStrategy === "static_baseline"
              ? {
                  model_type: staticBaselineConfig.model_type,
                  model_params: cleanedParams,
                  training_window_size: staticBaselineConfig.training_window_size,
                  calibration_fraction: staticBaselineConfig.calibration_fraction,
                  conformal_strategy: "split",
                  fdr_config:
                    staticBaselineConfig.fdr_method === "saffron"
                      ? {
                          method: "saffron",
                          alpha: staticBaselineConfig.fdr_alpha,
                          wealth: staticBaselineConfig.fdr_wealth,
                          lambda_: staticBaselineConfig.fdr_lambda,
                        }
                      : {
                          method: "naive",
                          cutoff: staticBaselineConfig.fdr_cutoff,
                        },
                }
              : undefined,
          adaptive_stream_config:
            monitoringStrategy === "adaptive_stream"
              ? {
                  model_type: selectedModelType,
                  model_params: cleanedParams,
                  preprocessing_steps: cleanedPreprocessingSteps,
                  performance_config: adaptivePerformanceConfig,
                }
              : undefined,
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
      <PageShell>
        <PageHeader
          eyebrow="Monitoring"
          title={`Charger ${chargerId}`}
          description="Configure a RADAR workload, inspect active services, and review recent findings for this charger."
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <MetricCard label="Sensors" value={monitoringKeys.length} helper="Available telemetry types" />
          <MetricCard label="Topics" value={effectiveTopics.length} helper="Effective MQTT subscriptions" tone="info" />
          <MetricCard label="Services" value={chargerServiceCount} helper="Active for this charger" tone={chargerServiceCount > 0 ? "success" : "default"} />
          <MetricCard label="Anomalies" value={anomalies.length} helper="Recently loaded detections" tone={anomalies.length > 0 ? "warning" : "default"} />
        </div>

        <MonitoringSectionCard
          title="Detection Setup"
          description="Build the topic set and choose the monitoring strategy."
          actions={
            <Button onClick={submitAnomalyDetection}>
              <Send className="h-4 w-4" />
              Start Monitoring
            </Button>
          }
        >
          <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
            <div className="min-w-0 space-y-6">
              <div className={PANEL_SECTION_CLASS}>
                <SectionEyebrow
                  icon={RadioTower}
                  title="Telemetry Scope"
                  description="Choose the telemetry streams this RADAR workload will subscribe to."
                />
                <div className="mt-4 space-y-2">
                  <label className={FIELD_LABEL_CLASS}>Topic Input Mode</label>
                  <select
                    className={FORM_CONTROL_CLASS}
                    value={topicMode}
                    onChange={(e) =>
                      setTopicMode(
                        e.target.value as "selected_sensors" | "direct_patterns"
                      )
                    }
                  >
                    <option value="selected_sensors">Build from selected sensors</option>
                    <option value="direct_patterns">Use direct topic patterns</option>
                  </select>
                </div>

                {topicMode === "selected_sensors" ? (
                  <div className="mt-4 space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="outline"
                            disabled={monitoringKeys.length === 0}
                          >
                            <Layers3 className="h-4 w-4" />
                            Sensor types
                            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                              {activeKeys.length} selected
                            </span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="max-h-80 w-64 overflow-y-auto">
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

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setVisibleMap(
                            Object.fromEntries(
                              monitoringKeys.map((key) => [key, true])
                            )
                          )
                        }
                      >
                        Select all
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setVisibleMap(
                            Object.fromEntries(
                              monitoringKeys.map((key) => [key, false])
                            )
                          )
                        }
                      >
                        Clear
                      </Button>
                    </div>

                    <div className="flex max-h-32 min-w-0 flex-wrap gap-2 overflow-y-auto rounded-md border border-dashed p-3">
                      {activeKeys.length > 0 ? (
                        activeKeys.map((key) => (
                          <span key={key} className={CHIP_CLASS}>
                            {key}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-muted-foreground">
                          No sensors selected.
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    <label className={FIELD_LABEL_CLASS}>Topic Patterns</label>
                    <textarea
                      className={cn(FORM_CONTROL_CLASS, "min-h-32 resize-y")}
                      value={topicPatternInput}
                      onChange={(e) => setTopicPatternInput(e.target.value)}
                      placeholder="One topic per line or comma-separated. Supports MQTT wildcards + and #."
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() =>
                        setTopicPatternInput(`charger/${chargerId}/live-telemetry/#`)
                      }
                    >
                      All charger telemetry
                    </Button>
                    <p className={FIELD_HELP_CLASS}>
                      Parsed topics:{" "}
                      {parseTopicPatterns(topicPatternInput).join(", ") || "none"}
                    </p>
                  </div>
                )}
              </div>

              <div className={PANEL_SECTION_CLASS}>
                <SectionEyebrow
                  icon={Settings2}
                  title="Runtime"
                  description="Shared subscription behavior for either strategy."
                />
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="flex flex-col">
                    <label className={FIELD_LABEL_CLASS}>Sensor Freshness (s)</label>
                    <input
                      type="number"
                      min={1}
                      step="1"
                      className={cn(FORM_CONTROL_CLASS, "mt-1")}
                      value={performanceConfig.sensor_freshness_seconds}
                      onChange={(event) =>
                        handlePerformanceNumberChange(
                          "sensor_freshness_seconds",
                          event.target.value
                        )
                      }
                    />
                  </div>
                  <div className="flex flex-col">
                    <label className={FIELD_LABEL_CLASS}>Sensor Strategy</label>
                    <select
                      className={cn(FORM_CONTROL_CLASS, "mt-1")}
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
                </div>
              </div>

              <div className={PANEL_SECTION_CLASS}>
                <SectionEyebrow
                  icon={RadioTower}
                  title="Effective Topics"
                  description={`${effectiveTopics.length} MQTT subscriptions will be sent to the service.`}
                />
                <div className="mt-4 max-h-44 min-w-0 space-y-2 overflow-y-auto rounded-md border bg-muted/20 p-3">
                  {effectiveTopics.length > 0 ? (
                    effectiveTopics.map((topic, index) => (
                      <div
                        key={`${topic}-${index}`}
                        className="block max-w-full truncate rounded-md bg-background px-3 py-2 font-mono text-xs"
                        title={topic}
                      >
                        {topic}
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No effective topics yet.
                    </p>
                  )}
                </div>
              </div>
            </div>

            <div className="min-w-0 space-y-6">
              <div className={PANEL_SECTION_CLASS}>
                <SectionEyebrow
                  icon={SlidersHorizontal}
                  title="Strategy"
                  description="Static trains once on a baseline; Dynamic adapts continuously."
                />
                <div className="mt-4 inline-flex rounded-md border bg-muted/30 p-1">
                  <button
                    type="button"
                    aria-pressed={monitoringStrategy === "static_baseline"}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-sm px-3 py-2 text-sm font-medium transition",
                      monitoringStrategy === "static_baseline"
                        ? "bg-background text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                    onClick={() => setMonitoringStrategy("static_baseline")}
                  >
                    <Database className="h-4 w-4" aria-hidden="true" />
                    Static
                  </button>
                  <button
                    type="button"
                    aria-pressed={monitoringStrategy === "adaptive_stream"}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-sm px-3 py-2 text-sm font-medium transition",
                      monitoringStrategy === "adaptive_stream"
                        ? "bg-background text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                    onClick={() => setMonitoringStrategy("adaptive_stream")}
                  >
                    <Activity className="h-4 w-4" aria-hidden="true" />
                    Dynamic
                  </button>
                </div>
              </div>

              {monitoringStrategy === "static_baseline" ? (
                <>
                  <div className={PANEL_SECTION_CLASS}>
                    <SectionEyebrow
                      icon={Database}
                      title="Static Baseline"
                      description="Detector and baseline parameters."
                    />
                    <label className="mt-4 block text-sm font-semibold">
                      Static Detector
                    </label>
                    <select
                      className={cn(FORM_CONTROL_CLASS, "mt-2")}
                      value={staticBaselineConfig.model_type}
                      onChange={(e) => handleStaticModelSelect(e.target.value)}
                      disabled={isLoadingModels}
                    >
                      <option value="" disabled>
                        {isLoadingModels ? "Loading models..." : "Select detector"}
                      </option>
                      {Object.keys(staticModels).map((key) => (
                        <option key={key} value={key}>
                          {key}
                        </option>
                      ))}
                    </select>
                    <div className={cn(QUIET_SURFACE_CLASS, "mt-4")}>
                      <div className="text-xs font-medium uppercase text-muted-foreground">
                        Picked Detector
                      </div>
                      <p className="mt-2 text-sm font-medium">
                      {staticModels[staticBaselineConfig.model_type]?.name ||
                        staticBaselineConfig.model_type ||
                        "None selected"}
                      </p>
                    </div>

                  <Button
                    type="button"
                    variant="outline"
                    className="mt-4"
                    onClick={() => setShowStaticAdvanced((value) => !value)}
                  >
                    <Settings2 className="h-4 w-4" />
                    {showStaticAdvanced ? "Hide configuration" : "Show configuration"}
                  </Button>

                  {showStaticAdvanced && (
                    <div className="mt-5 space-y-6">
                      {staticBaselineConfig.model_type && (
                        <div className="space-y-3">
                          <h3 className="text-sm font-semibold">Detector Parameters</h3>
                          {Object.entries(staticModels[staticBaselineConfig.model_type]?.parameters?.properties || {}).length === 0 && (
                            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">No parameters for this detector.</p>
                          )}
                          <div className="grid gap-3 sm:grid-cols-2">
                          {Object.entries(staticModels[staticBaselineConfig.model_type]?.parameters?.properties || {}).map(
                            ([key, schema]) => (
                              <div key={key} className="flex flex-col">
                                <label className="mb-1 text-sm font-medium">
                                  {key}
                                  {schema?.description ? (
                                    <span className="ml-1 text-xs text-muted-foreground">({schema.description})</span>
                                  ) : null}
                                </label>
                                <input
                                  type={getInputType(schema?.type)}
                                  className={FORM_CONTROL_CLASS}
                                  checked={
                                    schema?.type === "boolean"
                                      ? Boolean(staticBaselineConfig.model_params[key])
                                      : undefined
                                  }
                                  value={
                                    schema?.type === "boolean"
                                      ? undefined
                                      : getTextInputValue(staticBaselineConfig.model_params[key])
                                  }
                                  onChange={(e) =>
                                    handleStaticParamChange(
                                      key,
                                      schema?.type === "boolean"
                                        ? e.target.checked
                                        : e.target.value,
                                      schema?.type
                                    )
                                  }
                                  min={schema?.minimum}
                                  max={schema?.maximum}
                                  step="any"
                                />
                              </div>
                            )
                          )}
                          </div>
                        </div>
                      )}

                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Training Window</h3>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Window Size</label>
                            <input
                              type="number"
                              min={20}
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.training_window_size}
                              onChange={(event) =>
                                handleStaticNumberChange(
                                  "training_window_size",
                                  event.target.value
                                )
                              }
                            />
                          </div>
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Calibration Fraction</label>
                            <input
                              type="number"
                              min={0.01}
                              max={0.94}
                              step="0.01"
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.calibration_fraction}
                              onChange={(event) =>
                                handleStaticNumberChange(
                                  "calibration_fraction",
                                  event.target.value
                                )
                              }
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">FDR Control</h3>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Method</label>
                            <select
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.fdr_method}
                              onChange={(event) =>
                                setStaticBaselineConfig((prev) => ({
                                  ...prev,
                                  fdr_method: event.target.value as FdrControlMethod,
                                }))
                              }
                            >
                              <option value="saffron">SAFFRON</option>
                              <option value="naive">Naive p-value cutoff</option>
                            </select>
                          </div>

                          {staticBaselineConfig.fdr_method === "naive" && (
                            <div className="flex flex-col">
                              <label className="mb-1 text-sm font-medium">Cutoff</label>
                              <input
                                type="number"
                                min={0.0001}
                                max={0.9999}
                                step="0.001"
                                className={FORM_CONTROL_CLASS}
                                value={staticBaselineConfig.fdr_cutoff}
                                onChange={(event) =>
                                  handleStaticNumberChange("fdr_cutoff", event.target.value)
                                }
                              />
                            </div>
                          )}
                        </div>

                        {staticBaselineConfig.fdr_method === "saffron" && (
                          <div className="grid gap-3 sm:grid-cols-3">
                            <div className="flex flex-col">
                              <label className="mb-1 text-sm font-medium">Alpha</label>
                              <input
                                type="number"
                                min={0.0001}
                                max={0.9999}
                                step="0.001"
                                className={FORM_CONTROL_CLASS}
                                value={staticBaselineConfig.fdr_alpha}
                                onChange={(event) =>
                                  handleStaticNumberChange("fdr_alpha", event.target.value)
                                }
                              />
                            </div>
                            <div className="flex flex-col">
                              <label className="mb-1 text-sm font-medium">Wealth</label>
                              <input
                                type="number"
                                min={0.0001}
                                max={0.9999}
                                step="0.001"
                                className={FORM_CONTROL_CLASS}
                                value={staticBaselineConfig.fdr_wealth}
                                onChange={(event) =>
                                  handleStaticNumberChange("fdr_wealth", event.target.value)
                                }
                              />
                            </div>
                            <div className="flex flex-col">
                              <label className="mb-1 text-sm font-medium">Lambda</label>
                              <input
                                type="number"
                                min={0.0001}
                                max={0.9999}
                                step="0.001"
                                className={FORM_CONTROL_CLASS}
                                value={staticBaselineConfig.fdr_lambda}
                                onChange={(event) =>
                                  handleStaticNumberChange("fdr_lambda", event.target.value)
                                }
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  </div>
                </>
              ) : (
                <>
                  <div className={PANEL_SECTION_CLASS}>
                    <SectionEyebrow
                      icon={Activity}
                      title="Adaptive Stream"
                      description="Streaming model and adaptive settings."
                    />
                    <label className="mt-4 block text-sm font-semibold">
                      Dynamic Model
                    </label>
                    <select
                      className={cn(FORM_CONTROL_CLASS, "mt-2")}
                      value={selectedAlgorithm || ""}
                      onChange={(e) => handleModelSelect(e.target.value)}
                      disabled={isLoadingModels}
                    >
                      <option value="" disabled>
                        {isLoadingModels ? "Loading models..." : "Select algorithm"}
                      </option>
                      {Object.keys(adaptiveModels).map((key) => (
                        <option key={key} value={key}>
                          {key}
                        </option>
                      ))}
                    </select>
                    <div className={cn(QUIET_SURFACE_CLASS, "mt-4")}>
                      <div className="text-xs font-medium uppercase text-muted-foreground">
                        Picked Algorithm
                      </div>
                      <p className="mt-2 text-sm font-medium">
                      {selectedAlgorithm
                        ? adaptiveModels[selectedAlgorithm]?.name || selectedAlgorithm
                        : "None selected"}
                      </p>
                    </div>

                  <Button
                    type="button"
                    variant="outline"
                    className="mt-4"
                    onClick={() => setShowDynamicAdvanced((value) => !value)}
                  >
                    <Settings2 className="h-4 w-4" />
                    {showDynamicAdvanced ? "Hide configuration" : "Show configuration"}
                  </Button>

                  {showDynamicAdvanced && (
                    <div className="mt-5 space-y-6">
                      {selectedAlgorithm && (
                        <div className="space-y-3">
                          <h3 className="text-sm font-semibold">Parameters</h3>
                          {Object.entries(adaptiveModels[selectedAlgorithm]?.parameters?.properties || {}).length === 0 && (
                            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">No parameters for this model.</p>
                          )}
                          <div className="grid gap-3 sm:grid-cols-2">
                          {Object.entries(adaptiveModels[selectedAlgorithm]?.parameters?.properties || {}).map(
                            ([key, schema]) => (
                              <div key={key} className="flex flex-col">
                                <label className="mb-1 text-sm font-medium">
                                  {key}
                                  {schema?.description ? (
                                    <span className="ml-1 text-xs text-muted-foreground">({schema.description})</span>
                                  ) : null}
                                </label>
                                <input
                                  type={getInputType(schema?.type)}
                                  className={FORM_CONTROL_CLASS}
                                  checked={
                                    schema?.type === "boolean"
                                      ? Boolean(modelParams[key])
                                      : undefined
                                  }
                                  value={
                                    schema?.type === "boolean"
                                      ? undefined
                                      : getTextInputValue(modelParams[key])
                                  }
                                  onChange={(e) =>
                                    handleParamChange(
                                      key,
                                      schema?.type === "boolean"
                                        ? e.target.checked
                                        : e.target.value,
                                      schema?.type
                                    )
                                  }
                                  min={schema?.minimum}
                                  max={schema?.maximum}
                                  step="any"
                                />
                              </div>
                            )
                          )}
                          </div>
                        </div>
                      )}

                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Detection Heuristics</h3>
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
                          Enable trailing-reference tail trigger
                        </label>
                        <div className="grid gap-3 sm:grid-cols-3">
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Window Size</label>
                            <input
                              type="number"
                              min={3}
                              className={FORM_CONTROL_CLASS}
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
                            <label className="mb-1 text-sm font-medium">Min Samples</label>
                            <input
                              type="number"
                              min={2}
                              className={FORM_CONTROL_CLASS}
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
                            <label className="mb-1 text-sm font-medium">Tail Alpha</label>
                            <input
                              type="number"
                              min={0.0001}
                              max={0.9999}
                              step="0.0001"
                              className={FORM_CONTROL_CLASS}
                              value={performanceConfig.heuristic_tail_alpha}
                              onChange={(event) =>
                                handlePerformanceNumberChange(
                                  "heuristic_tail_alpha",
                                  event.target.value
                                )
                              }
                            />
                          </div>
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
                  )}
                  </div>
                </>
              )}
            </div>
          </div>
        </MonitoringSectionCard>

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
      </PageShell>
    </>
  );
};

export default Monitoring;
