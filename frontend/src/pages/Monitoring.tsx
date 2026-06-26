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
import {
  getOperationalStageDisplay,
  getStatusDisplay,
} from "@/types/monitoring";
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
  ModelDefinition,
  ModelParams,
  OperationalStatus,
  ParameterSchema,
  PreprocessingStepConfig,
  PreprocessorDefinition,
} from "@/types/monitoring";

type ConfigValue = string | number | boolean;
type ConfigInputValue = string | boolean;
type FieldErrors = Record<string, string>;
type InputErrorProps = {
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
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

const getFieldErrorId = (fieldKey: string): string =>
  `monitoring-${fieldKey.replace(/[^a-zA-Z0-9_-]/g, "-")}-error`;

const parseDraftNumber = ({
  fieldKey,
  label,
  value,
  schemaType,
  min,
  max,
  required = true,
  errors,
}: {
  fieldKey: string;
  label: string;
  value: unknown;
  schemaType: "integer" | "number";
  min?: number;
  max?: number;
  required?: boolean;
  errors: FieldErrors;
}): number | undefined => {
  const raw = String(value ?? "").trim();
  if (raw === "") {
    if (required) errors[fieldKey] = `${label} is required.`;
    return undefined;
  }

  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    errors[fieldKey] = `${label} must be a number.`;
    return undefined;
  }
  if (schemaType === "integer" && !Number.isInteger(parsed)) {
    errors[fieldKey] = `${label} must be an integer.`;
    return undefined;
  }
  if (min !== undefined && parsed < min) {
    errors[fieldKey] = `${label} must be at least ${min}.`;
    return undefined;
  }
  if (max !== undefined && parsed > max) {
    errors[fieldKey] = `${label} must be at most ${max}.`;
    return undefined;
  }
  return parsed;
};

const coerceConfigParams = (
  params: ModelParams | Record<string, ConfigValue> | undefined,
  properties: Record<string, ParameterSchema>,
  requiredKeys: string[] | undefined,
  prefix: string,
  errors: FieldErrors
): ModelParams => {
  const cleaned: ModelParams = {};
  const required = new Set(requiredKeys || []);
  const keys = new Set([
    ...Object.keys(params || {}),
    ...required,
  ]);

  keys.forEach((key) => {
    const value = params?.[key];
    const schema = properties[key];
    const fieldKey = `${prefix}.${key}`;
    const isEmpty = value === "" || value === undefined;

    if (schema?.type === "boolean") {
      cleaned[key] = Boolean(value);
      return;
    }
    if (isEmpty) {
      if (required.has(key)) errors[fieldKey] = `${key} is required.`;
      return;
    }
    if (schema?.type === "integer" || schema?.type === "number") {
      const parsed = parseDraftNumber({
        fieldKey,
        label: key,
        value,
        schemaType: schema.type,
        min: schema.minimum,
        max: schema.maximum,
        required: required.has(key),
        errors,
      });
      if (parsed !== undefined) cleaned[key] = parsed;
      return;
    }
    if (isConfigValue(value)) cleaned[key] = value;
  });

  return cleaned;
};

type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";
type AlignmentMode = "strict_barrier";
type MonitoringStrategy = "static_baseline" | "adaptive_stream";

type PerformanceConfigState = {
  heuristic_enabled: boolean;
  heuristic_window_size: string;
  heuristic_min_samples: string;
  heuristic_tail_alpha: string;
  alignment_mode: AlignmentMode;
  sensor_key_strategy: SensorKeyStrategy;
  sensor_freshness_seconds: string;
};

type StaticBaselineConfigState = {
  model_type: string;
  model_params: ModelParams;
  training_window_size: string;
  calibration_window_size: string;
  martingale_alpha: string;
  martingale_epsilon: string;
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
  "h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 disabled:pointer-events-none disabled:opacity-50";
const PRIMARY_ACTION_BUTTON_CLASS = "";
const FIELD_LABEL_CLASS = "text-sm font-medium text-foreground";
const FIELD_HELP_CLASS = "mt-1 text-xs leading-5 text-muted-foreground";
const FIELD_ERROR_CLASS = "mt-1 text-xs leading-5 text-destructive";
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

const FieldError: React.FC<{ fieldKey: string; errors: FieldErrors }> = ({
  fieldKey,
  errors,
}) => {
  const message = errors[fieldKey];
  if (!message) return null;
  return (
    <p id={getFieldErrorId(fieldKey)} className={FIELD_ERROR_CLASS}>
      {message}
    </p>
  );
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

const OperationalStageSummary: React.FC<{ status: OperationalStatus }> = ({
  status,
}) => {
  const stage = getOperationalStageDisplay(status);
  const progress = status.progress;
  const percent = progress
    ? Math.min(100, Math.round((progress.current / Math.max(progress.target, 1)) * 100))
    : 0;

  return (
    <div className="mt-2">
      <StatusPill label={stage.label} className={stage.className} />
      {progress ? (
        <div className="mt-2 w-36">
          <div className="mb-1 text-xs text-muted-foreground">
            {progress.current}/{progress.target}
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      ) : status.detail ? (
        <div className="mt-1 max-w-40 text-xs text-muted-foreground">
          {status.detail}
        </div>
      ) : null}
      {status.is_stale ? (
        <div className="mt-1 text-xs text-yellow-700 dark:text-yellow-300">
          Stale heartbeat
        </div>
      ) : null}
    </div>
  );
};

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
  fieldErrors: FieldErrors;
  inputErrorProps: (fieldKey: string) => InputErrorProps;
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
  fieldErrors,
  inputErrorProps,
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
              {Object.entries(schemaProps).map(([key, schema]) => {
                const fieldKey = `preprocessors.${index}.params.${key}`;
                return (
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
                          schema?.type === "boolean"
                            ? e.target.checked
                            : e.target.value,
                          schema?.type
                        )
                      }
                      min={schema?.minimum}
                      max={schema?.maximum}
                      step="any"
                      {...inputErrorProps(fieldKey)}
                    />
                    <FieldError fieldKey={fieldKey} errors={fieldErrors} />
                  </div>
                );
              })}
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
                    <OperationalStageSummary
                      status={service.operational_status}
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
  const defaultTopicPattern = chargerId
    ? `charger/${chargerId}/live-telemetry/#`
    : "";
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
    () => monitoringKeys.filter((key) => visibleMap[key] ?? true),
    [monitoringKeys, visibleMap]
  );
  const [topicMode, setTopicMode] = useState<"selected_sensors" | "direct_patterns">(
    "selected_sensors"
  );
  const [topicPatternInput, setTopicPatternInput] =
    useState<string>(defaultTopicPattern);
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
    heuristic_window_size: "1000",
    heuristic_min_samples: "300",
    heuristic_tail_alpha: "0.005",
    alignment_mode: "strict_barrier",
    sensor_key_strategy: "full_hierarchy",
    sensor_freshness_seconds: "30",
  });
  const [staticBaselineConfig, setStaticBaselineConfig] =
    useState<StaticBaselineConfigState>({
      model_type: DEFAULT_STATIC_MODEL_TYPE,
      model_params: DEFAULT_STATIC_MODEL_PARAMS,
      training_window_size: "1200",
      calibration_window_size: "360",
      martingale_alpha: "0.01",
      martingale_epsilon: "0.5",
    });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
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

  const clearFieldError = useCallback((fieldKey: string) => {
    setFieldErrors((prev) => {
      if (!prev[fieldKey]) return prev;
      const next = { ...prev };
      delete next[fieldKey];
      return next;
    });
  }, []);

  const inputErrorProps = useCallback(
    (fieldKey: string): InputErrorProps =>
      fieldErrors[fieldKey]
        ? {
            "aria-invalid": true,
            "aria-describedby": getFieldErrorId(fieldKey),
          }
        : {},
    [fieldErrors]
  );

  useEffect(() => {
    if (!chargerId) return;

    loadAllTelemetryTypes(chargerId);
  }, [loadAllTelemetryTypes, chargerId]);

  useEffect(() => {
    if (!chargerId) return;
    const timeoutId = window.setTimeout(() => {
      setTopicPatternInput(defaultTopicPattern);
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [chargerId, defaultTopicPattern]);

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
    const timeoutId = window.setTimeout(() => {
      void loadModels();
    }, 0);

    return () => window.clearTimeout(timeoutId);
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
    const timeoutId = window.setTimeout(() => {
      void loadPreprocessors();
    }, 0);

    return () => window.clearTimeout(timeoutId);
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
    void schemaType;
    setModelParams((prev) => ({ ...prev, [key]: rawValue }));
    clearFieldError(`dynamic.model_params.${key}`);
  }, [clearFieldError]);

  const handleStaticParamChange = useCallback((key: string, rawValue: ConfigInputValue, schemaType?: string) => {
    void schemaType;
    setStaticBaselineConfig((prev) => ({
      ...prev,
      model_params: { ...prev.model_params, [key]: rawValue },
    }));
    clearFieldError(`static.model_params.${key}`);
  }, [clearFieldError]);

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
    (index: number, key: string, rawValue: ConfigInputValue) => {
      setPreprocessingSteps((prev) => {
        const updated = [...prev];
        updated[index] = {
          ...updated[index],
          params: { ...(updated[index].params || {}), [key]: rawValue },
        };
        return updated;
      });
      clearFieldError(`preprocessors.${index}.params.${key}`);
    },
    [clearFieldError]
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
      setPerformanceConfig((prev) => ({
        ...prev,
        [key]: rawValue,
      }));
      clearFieldError(`performance.${key}`);
    },
    [clearFieldError]
  );

  const handleStaticNumberChange = useCallback(
    (
      key:
        | "training_window_size"
        | "calibration_window_size"
        | "martingale_alpha"
        | "martingale_epsilon",
      rawValue: string
    ) => {
      setStaticBaselineConfig((prev) => ({
        ...prev,
        [key]: rawValue,
      }));
      clearFieldError(`static.${key}`);
    },
    [clearFieldError]
  );

  useEffect(() => {
    const staticKeys = Object.keys(staticModels);
    if (staticKeys.length === 0) return;
    if (staticBaselineConfig.model_type in staticModels) return;
    const modelType =
      staticKeys.includes(DEFAULT_STATIC_MODEL_TYPE)
        ? DEFAULT_STATIC_MODEL_TYPE
        : staticKeys[0];
    const timeoutId = window.setTimeout(() => {
      handleStaticModelSelect(modelType);
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [handleStaticModelSelect, staticBaselineConfig.model_type, staticModels]);

  useEffect(() => {
    const adaptiveKeys = Object.keys(adaptiveModels);
    if (adaptiveKeys.length === 0) return;
    if (selectedAlgorithm && selectedAlgorithm in adaptiveModels) return;
    const modelType = adaptiveKeys.includes(DEFAULT_MODEL_TYPE)
      ? DEFAULT_MODEL_TYPE
      : adaptiveKeys[0];
    const timeoutId = window.setTimeout(() => {
      handleModelSelect(modelType);
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [adaptiveModels, handleModelSelect, selectedAlgorithm]);

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
    const timeoutId = window.setTimeout(() => {
      void loadActiveServices();
    }, 0);

    // Refresh services every 30 seconds
    const interval = window.setInterval(() => {
      void loadActiveServices();
    }, 30000);

    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(interval);
    };
  }, [loadActiveServices]);

  // Load anomalies on component mount and set up refresh interval
  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadAnomalies();
    }, 0);

    // Refresh anomalies every 30 seconds
    const anomalyInterval = window.setInterval(() => {
      void loadAnomalies();
    }, 30000);

    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(anomalyInterval);
    };
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

      // Generate unique container name
      const containerName = `radar-${chargerId}-${Date.now()}`;
      const errors: FieldErrors = {};
      const selectedModelInfo =
        monitoringStrategy === "static_baseline"
          ? staticModels[selectedModelType]
          : adaptiveModels[selectedModelType];

      const activeModelParams =
        monitoringStrategy === "static_baseline"
          ? staticBaselineConfig.model_params
          : modelParams;
      const cleanedParams = coerceConfigParams(
        activeModelParams,
        selectedModelInfo?.parameters?.properties || {},
        selectedModelInfo?.parameters?.required,
        monitoringStrategy === "static_baseline"
          ? "static.model_params"
          : "dynamic.model_params",
        errors
      );

      const cleanedPreprocessingSteps =
        monitoringStrategy === "adaptive_stream"
          ? preprocessingSteps.map((step, index) => ({
              type: step.type,
              params: coerceConfigParams(
                step.params || {},
                availablePreprocessors[step.type]?.parameters?.properties || {},
                availablePreprocessors[step.type]?.parameters?.required,
                `preprocessors.${index}.params`,
                errors
              ),
            }))
          : [];

      const sensorFreshnessSeconds = parseDraftNumber({
        fieldKey: "performance.sensor_freshness_seconds",
        label: "Sensor freshness",
        value: performanceConfig.sensor_freshness_seconds,
        schemaType: "number",
        min: 1,
        errors,
      });

      const heuristicWindowSize =
        monitoringStrategy === "adaptive_stream"
          ? parseDraftNumber({
              fieldKey: "performance.heuristic_window_size",
              label: "Heuristic window size",
              value: performanceConfig.heuristic_window_size,
              schemaType: "integer",
              min: 3,
              errors,
            })
          : undefined;
      const heuristicMinSamples =
        monitoringStrategy === "adaptive_stream"
          ? parseDraftNumber({
              fieldKey: "performance.heuristic_min_samples",
              label: "Heuristic min samples",
              value: performanceConfig.heuristic_min_samples,
              schemaType: "integer",
              min: 2,
              errors,
            })
          : undefined;
      const heuristicTailAlpha =
        monitoringStrategy === "adaptive_stream"
          ? parseDraftNumber({
              fieldKey: "performance.heuristic_tail_alpha",
              label: "Heuristic tail alpha",
              value: performanceConfig.heuristic_tail_alpha,
              schemaType: "number",
              min: 0.0001,
              max: 0.9999,
              errors,
            })
          : undefined;
      if (
        heuristicWindowSize !== undefined &&
        heuristicMinSamples !== undefined &&
        heuristicMinSamples > heuristicWindowSize
      ) {
        errors["performance.heuristic_min_samples"] =
          "Heuristic min samples must be less than or equal to window size.";
      }

      const trainingWindowSize =
        monitoringStrategy === "static_baseline"
          ? parseDraftNumber({
              fieldKey: "static.training_window_size",
              label: "Training window size",
              value: staticBaselineConfig.training_window_size,
              schemaType: "integer",
              min: 20,
              errors,
            })
          : undefined;
      const calibrationWindowSize =
        monitoringStrategy === "static_baseline"
          ? parseDraftNumber({
              fieldKey: "static.calibration_window_size",
              label: "Calibration samples",
              value: staticBaselineConfig.calibration_window_size,
              schemaType: "integer",
              min: 1,
              errors,
            })
          : undefined;
      const martingaleAlpha =
        monitoringStrategy === "static_baseline"
          ? parseDraftNumber({
              fieldKey: "static.martingale_alpha",
              label: "Martingale alpha",
              value: staticBaselineConfig.martingale_alpha,
              schemaType: "number",
              min: 0.0001,
              max: 0.9999,
              errors,
            })
          : undefined;
      const martingaleEpsilon =
        monitoringStrategy === "static_baseline"
          ? parseDraftNumber({
              fieldKey: "static.martingale_epsilon",
              label: "Martingale epsilon",
              value: staticBaselineConfig.martingale_epsilon,
              schemaType: "number",
              min: 0.0001,
              max: 1,
              errors,
            })
          : undefined;

      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        toast.error("Fix highlighted configuration fields before starting monitoring.");
        return;
      }
      setFieldErrors({});

      const commonPerformanceConfig = {
        alignment_mode: performanceConfig.alignment_mode,
        sensor_key_strategy: performanceConfig.sensor_key_strategy,
        sensor_freshness_seconds: sensorFreshnessSeconds!,
      };

      const adaptivePerformanceConfig = {
        ...commonPerformanceConfig,
        heuristic_enabled: performanceConfig.heuristic_enabled,
        heuristic_window_size: heuristicWindowSize!,
        heuristic_min_samples: heuristicMinSamples!,
        heuristic_tail_alpha: heuristicTailAlpha!,
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
                  training_window_size: trainingWindowSize!,
                  calibration_window_size: calibrationWindowSize!,
                  conformal_strategy: "split",
                  martingale_config: {
                    method: "power",
                    alpha: martingaleAlpha!,
                    epsilon: martingaleEpsilon!,
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
                              checked={visibleMap[key] ?? true}
                              onCheckedChange={(checked) =>
                                setVisibleMap((prev) => ({
                                  ...prev,
                                  [key]: checked === true,
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
                      {...inputErrorProps("performance.sensor_freshness_seconds")}
                    />
                    <FieldError
                      fieldKey="performance.sensor_freshness_seconds"
                      errors={fieldErrors}
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
                            ([key, schema]) => {
                              const fieldKey = `static.model_params.${key}`;
                              return (
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
                                    {...inputErrorProps(fieldKey)}
                                  />
                                  <FieldError fieldKey={fieldKey} errors={fieldErrors} />
                                </div>
                              );
                            }
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
                              {...inputErrorProps("static.training_window_size")}
                            />
                            <FieldError
                              fieldKey="static.training_window_size"
                              errors={fieldErrors}
                            />
                          </div>
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Calibration Samples</label>
                            <input
                              type="number"
                              min={1}
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.calibration_window_size}
                              onChange={(event) =>
                                handleStaticNumberChange(
                                  "calibration_window_size",
                                  event.target.value
                                )
                              }
                              {...inputErrorProps("static.calibration_window_size")}
                            />
                            <FieldError
                              fieldKey="static.calibration_window_size"
                              errors={fieldErrors}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Martingale Alarm</h3>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Alpha</label>
                            <input
                              type="number"
                              min={0.0001}
                              max={0.9999}
                              step="0.001"
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.martingale_alpha}
                              onChange={(event) =>
                                handleStaticNumberChange("martingale_alpha", event.target.value)
                              }
                              {...inputErrorProps("static.martingale_alpha")}
                            />
                            <FieldError
                              fieldKey="static.martingale_alpha"
                              errors={fieldErrors}
                            />
                          </div>
                          <div className="flex flex-col">
                            <label className="mb-1 text-sm font-medium">Epsilon</label>
                            <input
                              type="number"
                              min={0.0001}
                              max={1}
                              step="0.01"
                              className={FORM_CONTROL_CLASS}
                              value={staticBaselineConfig.martingale_epsilon}
                              onChange={(event) =>
                                handleStaticNumberChange("martingale_epsilon", event.target.value)
                              }
                              {...inputErrorProps("static.martingale_epsilon")}
                            />
                            <FieldError
                              fieldKey="static.martingale_epsilon"
                              errors={fieldErrors}
                            />
                          </div>
                        </div>
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
                            ([key, schema]) => {
                              const fieldKey = `dynamic.model_params.${key}`;
                              return (
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
                                    {...inputErrorProps(fieldKey)}
                                  />
                                  <FieldError fieldKey={fieldKey} errors={fieldErrors} />
                                </div>
                              );
                            }
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
                              {...inputErrorProps("performance.heuristic_window_size")}
                            />
                            <FieldError
                              fieldKey="performance.heuristic_window_size"
                              errors={fieldErrors}
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
                              {...inputErrorProps("performance.heuristic_min_samples")}
                            />
                            <FieldError
                              fieldKey="performance.heuristic_min_samples"
                              errors={fieldErrors}
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
                              {...inputErrorProps("performance.heuristic_tail_alpha")}
                            />
                            <FieldError
                              fieldKey="performance.heuristic_tail_alpha"
                              errors={fieldErrors}
                            />
                          </div>
                        </div>
                      </div>

                      <PreprocessingSection
                        steps={preprocessingSteps}
                        availablePreprocessors={availablePreprocessors}
                        newPreprocessorType={newPreprocessorType}
                        isLoading={isLoadingPreprocessors}
                        fieldErrors={fieldErrors}
                        inputErrorProps={inputErrorProps}
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
