import { NavigationBar } from "@/components/NavigationBar";
import { MetricCard, PageHeader, PageShell, SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useFetch } from "@/dataFetch/UseFetch";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { formatAnomalySensorSet } from "@/lib/anomaly-utils";
import { formatAnomalyValue, getAnomalyValueLabel } from "@/lib/anomaly-semantics";
import { cn } from "@/lib/utils";
import type { Anomaly } from "@/types/charger";
import { getOperationalStageDisplay, getServiceDeleteActionDisplay, getStatusDisplay } from "@/types/monitoring";
import type { ActiveService, ModelDefinition, ModelParams } from "@/types/monitoring";
import {
  Activity, CheckCircle2, Clock3, Database, FlaskConical, Layers3,
  ChevronDown, LockKeyhole, RadioTower, RefreshCw, Send, Settings2, ShieldCheck,
  Sparkles, Trash2,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { useParams } from "react-router-dom";

type ConfigValue = string | number | boolean;
type FieldErrors = Record<string, string>;
type TopicMode = "selected_sensors" | "direct_patterns";
type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";
type StaticDraft = {
  modelType: string;
  modelParams: Record<string, ConfigValue>;
  trainingWindow: string;
  calibrationWindow: string;
  epsilon: string;
  sensorFreshness: string;
  sensorKeyStrategy: SensorKeyStrategy;
};

const DEFAULT_MODEL_TYPE = "pyod_iforest";
const FIXED_VILLE_THRESHOLD = 100;
const DEFAULT_MODEL_PARAMS: Record<string, ConfigValue> = {
  n_estimators: 100,
  contamination: 0.1,
  random_state: 42,
};
const CONTROL_CLASS =
  "h-10 w-full rounded-lg border border-input bg-card px-3 py-2 text-sm shadow-xs outline-none transition-[border-color,box-shadow] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 aria-invalid:border-destructive";
const LABEL_CLASS = "text-sm font-medium text-foreground";
const HELP_CLASS = "mt-1 text-xs leading-5 text-muted-foreground";
const ERROR_CLASS = "mt-1 text-xs leading-5 text-destructive";

const parseTopicPatterns = (raw: string): string[] =>
  raw.split(/[\n,]/).map((topic) => topic.trim()).filter(Boolean);
const humanize = (value: string): string =>
  value.replace(/^pyod_/, "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const mqttFiltersOverlap = (left: string, right: string): boolean => {
  const a = left.trim().split("/");
  const b = right.trim().split("/");
  let index = 0;
  while (index < a.length && index < b.length) {
    if (a[index] === "#" || b[index] === "#") return true;
    if (a[index] !== "+" && b[index] !== "+" && a[index] !== b[index]) return false;
    index += 1;
  }
  if (index === a.length && index === b.length) return true;
  if (index < a.length) return index === a.length - 1 && a[index] === "#";
  return index === b.length - 1 && b[index] === "#";
};

const parseNumber = ({
  value, label, field, errors, integer = false, min, max,
}: {
  value: ConfigValue | undefined;
  label: string;
  field: string;
  errors: FieldErrors;
  integer?: boolean;
  min?: number;
  max?: number;
}): number | undefined => {
  const raw = String(value ?? "").trim();
  if (!raw) {
    errors[field] = `${label} is required.`;
    return undefined;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) errors[field] = `${label} must be a number.`;
  else if (integer && !Number.isInteger(parsed)) errors[field] = `${label} must be an integer.`;
  else if (min !== undefined && parsed < min) errors[field] = `${label} must be at least ${min}.`;
  else if (max !== undefined && parsed > max) errors[field] = `${label} must be at most ${max}.`;
  else return parsed;
  return undefined;
};

const coerceModelParams = (
  params: Record<string, ConfigValue>,
  definition: ModelDefinition | undefined,
  errors: FieldErrors
): ModelParams => {
  const cleaned: ModelParams = {};
  const properties = definition?.parameters?.properties ?? {};
  const required = new Set(definition?.parameters?.required ?? []);
  new Set([...Object.keys(params), ...required]).forEach((key) => {
    const schema = properties[key];
    const value = params[key];
    const field = `model.${key}`;
    if (schema?.type === "boolean") cleaned[key] = Boolean(value);
    else if (value === "" || value === undefined) {
      if (required.has(key)) errors[field] = `${humanize(key)} is required.`;
    } else if (schema?.type === "integer" || schema?.type === "number") {
      const parsed = parseNumber({
        value, label: humanize(key), field, errors,
        integer: schema.type === "integer", min: schema.minimum, max: schema.maximum,
      });
      if (parsed !== undefined) cleaned[key] = parsed;
    } else cleaned[key] = value;
  });
  return cleaned;
};

const errorId = (field: string) => `monitoring-${field.replace(/[^a-zA-Z0-9_-]/g, "-")}-error`;
const FieldError = ({ field, errors }: { field: string; errors: FieldErrors }) =>
  errors[field] ? <p id={errorId(field)} className={ERROR_CLASS}>{errors[field]}</p> : null;

const LifecycleStep = ({
  number, title, description, icon: Icon,
}: {
  number: number;
  title: string;
  description: string;
  icon: React.ElementType;
}) => (
  <div className="relative rounded-2xl border border-border/65 bg-card p-5">
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
          Phase {String(number).padStart(2, "0")}
        </div>
        <h3 className="mt-2 font-semibold tracking-[-0.01em]">{title}</h3>
      </div>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/[0.08] text-primary">
        <Icon className="size-4" />
      </span>
    </div>
    <p className="mt-4 text-sm leading-6 text-muted-foreground">{description}</p>
    <div className="mt-5 h-1 overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary/70" style={{ width: `${number * 33.333}%` }} />
    </div>
  </div>
);

const LaneCard = ({
  title, eyebrow, description, selected, icon: Icon,
}: {
  title: string;
  eyebrow: string;
  description: string;
  selected?: boolean;
  icon: React.ElementType;
}) => (
  <div
    className={cn(
      "relative overflow-hidden rounded-2xl border p-5 transition-colors sm:p-6",
      selected
        ? "border-primary/35 bg-primary/[0.035]"
        : "border-dashed border-border/70 bg-muted/15"
    )}
    aria-disabled={!selected}
  >
    <div className="flex items-start justify-between gap-4">
      <span className={cn(
        "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em]",
        selected ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
      )}>{eyebrow}</span>
      <span className={cn(
        "flex size-10 items-center justify-center rounded-xl",
        selected ? "bg-primary text-primary-foreground" : "border bg-card text-muted-foreground"
      )}>
        <Icon className="size-4" />
      </span>
    </div>
    <h3 className="mt-5 text-lg font-semibold tracking-[-0.02em]">{title}</h3>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
    <div className="mt-5 flex items-center gap-2 border-t border-border/60 pt-4 text-xs font-medium">
      {selected ? <><CheckCircle2 className="h-4 w-4 text-emerald-600" />Available now</> :
        <><Clock3 className="h-4 w-4" />Coming later</>}
    </div>
  </div>
);

const ConfigSection = ({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) => (
  <section className="rounded-2xl border border-border/65 bg-muted/[0.16] p-5 sm:p-6">
    <div className="flex items-start gap-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/[0.07] text-primary">
        <Icon className="size-4" />
      </span>
      <div>
        <h3 className="font-semibold tracking-[-0.01em]">{title}</h3>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
    <div className="mt-5">{children}</div>
  </section>
);

const Monitoring: React.FC = () => {
  const { chargerId } = useParams<{ chargerId: string }>();
  const { allTelemetryMap, loadAllTelemetryTypes } = useFetch();

  const [models, setModels] = useState<Record<string, ModelDefinition>>({});
  const [draft, setDraft] = useState<StaticDraft>({
    modelType: DEFAULT_MODEL_TYPE,
    modelParams: DEFAULT_MODEL_PARAMS,
    trainingWindow: "1200",
    calibrationWindow: "360",
    epsilon: "0.5",
    sensorFreshness: "30",
    sensorKeyStrategy: "full_hierarchy",
  });
  const [topicMode, setTopicMode] = useState<TopicMode>("selected_sensors");
  const [topicPatternInput, setTopicPatternInput] = useState("");
  const [selectedSensors, setSelectedSensors] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [services, setServices] = useState<ActiveService[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loadingServices, setLoadingServices] = useState(false);
  const [loadingAnomalies, setLoadingAnomalies] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [starting, setStarting] = useState(false);

  const sensorTypes = useMemo(
    () => (allTelemetryMap[chargerId ?? ""] ?? []).map((entry) => entry.type),
    [allTelemetryMap, chargerId]
  );
  const staticModels = useMemo(
    () => Object.fromEntries(Object.entries(models).filter(
      ([, model]) => model.strategy === "static_baseline"
    )),
    [models]
  );
  const topicForSensor = useCallback(
    (sensor: string) => `charger/${chargerId}/live-telemetry/${sensor}`,
    [chargerId]
  );
  const claimsBySensor = useMemo(() => {
    const claims = new Map<string, ActiveService>();
    sensorTypes.forEach((sensor) => {
      const concrete = topicForSensor(sensor);
      const owner = services.find((service) =>
        (service.mqtt_topics ?? []).some((topic) => mqttFiltersOverlap(topic, concrete))
      );
      if (owner) claims.set(sensor, owner);
    });
    return claims;
  }, [sensorTypes, services, topicForSensor]);
  const availableSelectedSensors = useMemo(
    () => sensorTypes.filter((sensor) => !claimsBySensor.has(sensor) && (selectedSensors[sensor] ?? true)),
    [claimsBySensor, selectedSensors, sensorTypes]
  );
  const effectiveTopics = useMemo(
    () => topicMode === "selected_sensors"
      ? availableSelectedSensors.map(topicForSensor)
      : parseTopicPatterns(topicPatternInput),
    [availableSelectedSensors, topicMode, topicForSensor, topicPatternInput]
  );
  const chargerServices = useMemo(
    () => services.filter((service) => (service.mqtt_topics ?? []).some(
      (topic) => topic.startsWith(`charger/${chargerId}/`) || topic.startsWith("charger/+/")
    )),
    [chargerId, services]
  );

  const clearError = useCallback((field: string) => {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);

  const loadModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      setModels(await apiUtils.get<Record<string, ModelDefinition>>(API_CONFIG.ENDPOINTS.MONITORING.MODELS) ?? {});
    } catch (error) {
      toast.error(`Failed to load static detectors: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setLoadingModels(false);
    }
  }, []);
  const loadServices = useCallback(async () => {
    setLoadingServices(true);
    try {
      setServices(await apiUtils.get<ActiveService[]>(
        `${API_CONFIG.ENDPOINTS.MONITORING.LIST}?active_only=true&include_docker_status=true`
      ) ?? []);
    } catch (error) {
      toast.error(`Failed to load services: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setLoadingServices(false);
    }
  }, []);
  const loadAnomalies = useCallback(async () => {
    if (!chargerId) return;
    setLoadingAnomalies(true);
    try {
      setAnomalies(await apiUtils.get<Anomaly[]>(API_CONFIG.ENDPOINTS.ANOMALIES.BY_CHARGER(chargerId)) ?? []);
    } catch (error) {
      toast.error(`Failed to load anomalies: ${error instanceof Error ? error.message : String(error)}`);
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
    }, 30000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
    };
  }, [loadAnomalies, loadModels, loadServices]);

  const selectModel = (modelType: string) => {
    const definition = staticModels[modelType];
    const defaults: Record<string, ConfigValue> = {};
    Object.entries(definition?.default_parameters ?? {}).forEach(([key, value]) => {
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") defaults[key] = value;
    });
    Object.entries(definition?.parameters?.properties ?? {}).forEach(([key, schema]) => {
      if (
        defaults[key] === undefined &&
        (typeof schema.default === "string" || typeof schema.default === "number" || typeof schema.default === "boolean")
      ) defaults[key] = schema.default;
    });
    setDraft((current) => ({
      ...current,
      modelType,
      modelParams: modelType === DEFAULT_MODEL_TYPE ? { ...defaults, ...DEFAULT_MODEL_PARAMS } : defaults,
    }));
    setFieldErrors({});
  };

  const deleteService = async (service: ActiveService) => {
    const action = getServiceDeleteActionDisplay(service);
    if (!window.confirm(action.confirmation)) return;
    try {
      await apiUtils.delete(
        API_CONFIG.ENDPOINTS.MONITORING.DELETE(service.id), undefined,
        { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT }
      );
      toast.success(action.success);
      await loadServices();
    } catch (error) {
      toast.error(`Failed to delete service: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const submit = async () => {
    if (!chargerId || !draft.modelType) return;
    const errors: FieldErrors = {};
    if (!effectiveTopics.length) errors.topics = "Select at least one unassigned sensor or enter a topic.";
    if (effectiveTopics.some((topic) => topic.split("/").some((part) => part === "+" || part === "#"))) {
      errors.topics = "Static monitoring requires concrete sensor topics without MQTT wildcards.";
    }
    if (effectiveTopics.some((topic) => topic.split("/")[1] !== chargerId)) {
      errors.topics = `All sensor topics must belong to charger ${chargerId}.`;
    }
    const trainingWindow = parseNumber({
      value: draft.trainingWindow, label: "Training samples", field: "trainingWindow",
      errors, integer: true, min: 20,
    });
    const calibrationWindow = parseNumber({
      value: draft.calibrationWindow, label: "Calibration samples", field: "calibrationWindow",
      errors, integer: true, min: 1,
    });
    const epsilon = parseNumber({
      value: draft.epsilon, label: "Power epsilon", field: "epsilon", errors, min: 0.0001, max: 1,
    });
    const sensorFreshness = parseNumber({
      value: draft.sensorFreshness, label: "Sensor freshness", field: "sensorFreshness", errors, min: 1,
    });
    const modelParams = coerceModelParams(draft.modelParams, staticModels[draft.modelType], errors);
    if (Object.keys(errors).length) {
      setFieldErrors(errors);
      toast.error("Fix the highlighted fields before starting monitoring.");
      return;
    }

    setStarting(true);
    try {
      await apiUtils.post(
        API_CONFIG.ENDPOINTS.MONITORING.START,
        {
          container_name: `radar-${chargerId}-${Date.now()}`,
          service_type: "radar",
          mqtt_topics: effectiveTopics,
          strategy: "static_baseline",
          model_type: draft.modelType,
          model_params: modelParams,
          performance_config: {
            alignment_mode: "strict_barrier",
            sensor_key_strategy: draft.sensorKeyStrategy,
            sensor_freshness_seconds: sensorFreshness,
          },
          static_baseline_config: {
            model_type: draft.modelType,
            model_params: modelParams,
            training_window_size: trainingWindow,
            calibration_window_size: calibrationWindow,
            conformal_strategy: "split",
            martingale_config: {
              method: "power",
              epsilon,
              restarted_ville_threshold: FIXED_VILLE_THRESHOLD,
            },
          },
        },
        { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT }
      );
      toast.success("Static monitoring service started.");
      await loadServices();
    } catch (error) {
      toast.error(`Failed to start monitoring: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setStarting(false);
    }
  };

  const modelDefinition = staticModels[draft.modelType];
  const modelProperties = modelDefinition?.parameters?.properties ?? {};

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
          <MetricCard label="Sensors" value={sensorTypes.length} helper="Discovered telemetry streams" />
          <MetricCard label="Available" value={sensorTypes.length - claimsBySensor.size} helper="Not assigned elsewhere" tone="info" />
          <MetricCard label="Services" value={chargerServices.length} helper="Active for this charger" tone={chargerServices.length ? "success" : "default"} />
          <MetricCard label="Alarms" value={anomalies.length} helper="Recent threshold crossings" tone={anomalies.length ? "warning" : "default"} />
        </div>

        <SectionPanel title="Choose a monitoring lane" description="Each lane has a distinct dependency assumption.">
          <div className="grid gap-4 lg:grid-cols-2">
            <LaneCard
              title="Static relationships" eyebrow="Selected"
              description="For signals such as L1, L2, and L3 whose dependency structure should remain stable. Train once, calibrate next, then produce online evidence."
              selected icon={Database}
            />
            <LaneCard
              title="Temporally dependent streams" eyebrow="Dynamic lane"
              description="Reserved for evolving temporal dependence. This is intentionally a façade only: no model, preprocessing, or runtime logic is attached yet."
              icon={Activity}
            />
          </div>
        </SectionPanel>

        <SectionPanel title="Static evidence lifecycle" description="Chronological samples; one purpose per phase.">
          <div className="grid gap-4 lg:grid-cols-3">
            <LifecycleStep number={1} title="Learn the baseline" description="Fit the detector on the first block of aligned sensor vectors." icon={Layers3} />
            <LifecycleStep number={2} title="Calibrate scores" description="Use a separate subsequent block to obtain conformal p-values." icon={FlaskConical} />
            <LifecycleStep number={3} title="Accumulate evidence" description="Transform p-values into e-values and update the native restarted mixture." icon={Sparkles} />
          </div>
        </SectionPanel>

        <SectionPanel
          title="Configure static monitoring"
          description="Select unassigned sensors, the detector, and the two sample blocks."
          actions={<Button onClick={submit} disabled={starting || loadingModels}><Send className="h-4 w-4" />{starting ? "Starting..." : "Start monitoring"}</Button>}
        >
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]">
            <div className="space-y-5">
              <ConfigSection
                title="Telemetry scope"
                description="Choose the concrete streams owned exclusively by this monitor."
                icon={RadioTower}
              >
                <label className={LABEL_CLASS}>Topic input mode</label>
                <select className={cn(CONTROL_CLASS, "mt-2")} value={topicMode} onChange={(event) => setTopicMode(event.target.value as TopicMode)}>
                  <option value="selected_sensors">Select discovered sensors</option>
                  <option value="direct_patterns">Enter MQTT topic patterns</option>
                </select>

                {topicMode === "selected_sensors" ? (
                  <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    {sensorTypes.map((sensor) => {
                      const owner = claimsBySensor.get(sensor);
                      const checked = !owner && (selectedSensors[sensor] ?? true);
                      return (
                        <label key={sensor} className={cn(
                          "flex items-start gap-3 rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow]",
                          owner
                            ? "cursor-not-allowed border-border/60 bg-muted/35 opacity-65"
                            : checked
                              ? "cursor-pointer border-primary/25 bg-primary/[0.035] shadow-xs"
                              : "cursor-pointer border-border/70 bg-card hover:border-primary/20"
                        )}>
                          <input
                            type="checkbox" className="mt-1 size-4 accent-primary" checked={checked} disabled={Boolean(owner)}
                            onChange={(event) => setSelectedSensors((current) => ({ ...current, [sensor]: event.target.checked }))}
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">{humanize(sensor)}</span>
                            <span className="block truncate text-xs text-muted-foreground">{owner ? `Assigned to ${owner.container_name}` : sensor}</span>
                          </span>
                        </label>
                      );
                    })}
                    {!sensorTypes.length && <p className="col-span-full rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No telemetry types discovered yet.</p>}
                  </div>
                ) : (
                  <div className="mt-4">
                    <textarea
                      className={cn(CONTROL_CLASS, "min-h-28 resize-y")} value={topicPatternInput}
                      onChange={(event) => setTopicPatternInput(event.target.value)}
                      placeholder={`One concrete sensor per line, e.g. charger/${chargerId}/live-telemetry/L1`}
                    />
                    <p className={HELP_CLASS}>Namespaces stay distinct. The backend verifies wildcard overlap before creation.</p>
                  </div>
                )}
                <FieldError field="topics" errors={fieldErrors} />
              </ConfigSection>

              <ConfigSection
                title="Baseline and sample windows"
                description="Select a static detector, then define its chronological training and calibration blocks."
                icon={Database}
              >
                <label className={LABEL_CLASS}>Detector</label>
                <select className={cn(CONTROL_CLASS, "mt-2")} value={draft.modelType} disabled={loadingModels} onChange={(event) => selectModel(event.target.value)}>
                  {!staticModels[draft.modelType] && <option value={draft.modelType}>{humanize(draft.modelType)}</option>}
                  {Object.entries(staticModels).map(([key, model]) => <option key={key} value={key}>{model.name || humanize(key)}</option>)}
                </select>
                <p className={HELP_CLASS}>{modelDefinition?.description || "A train-once PyOD detector for stable multivariate structure."}</p>

                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                {([
                  ["trainingWindow", "Training samples", 20, "Phase 1: fit the fixed baseline."],
                  ["calibrationWindow", "Calibration samples", 1, "Phase 2: calibrate on later data."],
                ] as const).map(([field, label, min, help]) => (
                  <div key={field}>
                    <label className={LABEL_CLASS}>{label}</label>
                    <input
                      type="number" min={min} className={cn(CONTROL_CLASS, "mt-2")}
                      value={draft[field]} aria-invalid={Boolean(fieldErrors[field])}
                      aria-describedby={fieldErrors[field] ? errorId(field) : undefined}
                      onChange={(event) => {
                        setDraft((current) => ({ ...current, [field]: event.target.value }));
                        clearError(field);
                      }}
                    />
                    <p className={HELP_CLASS}>{help}</p>
                    <FieldError field={field} errors={fieldErrors} />
                  </div>
                ))}
                </div>
              </ConfigSection>

              <Button type="button" variant="outline" className="w-full justify-between" onClick={() => setShowAdvanced((current) => !current)}>
                <span className="flex items-center gap-2"><Settings2 className="h-4 w-4" />{showAdvanced ? "Hide advanced settings" : "Show advanced settings"}</span>
                <ChevronDown className={cn("size-4 transition-transform", showAdvanced && "rotate-180")} />
              </Button>

              {showAdvanced && (
                <div className="space-y-6 rounded-2xl border border-border/65 bg-muted/[0.16] p-5 sm:p-6">
                  <div>
                    <h3 className="font-semibold">Detector parameters</h3>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {Object.entries(modelProperties).map(([key, schema]) => {
                        const field = `model.${key}`;
                        const value = draft.modelParams[key];
                        return (
                          <div key={key}>
                            <label className={LABEL_CLASS}>{humanize(key)}</label>
                            {schema.enum ? (
                              <select
                                className={cn(CONTROL_CLASS, "mt-2")} value={String(value ?? "")}
                                onChange={(event) => {
                                  setDraft((current) => ({ ...current, modelParams: { ...current.modelParams, [key]: event.target.value } }));
                                  clearError(field);
                                }}
                              >
                                {schema.enum.map((option) => <option key={String(option)} value={String(option)}>{humanize(String(option))}</option>)}
                              </select>
                            ) : schema.type === "boolean" ? (
                              <label className="mt-3 flex items-center gap-2 text-sm">
                                <input
                                  type="checkbox" className="size-4 accent-primary" checked={Boolean(value)}
                                  onChange={(event) => {
                                    setDraft((current) => ({ ...current, modelParams: { ...current.modelParams, [key]: event.target.checked } }));
                                    clearError(field);
                                  }}
                                />Enabled
                              </label>
                            ) : (
                              <input
                                type={schema.type === "integer" || schema.type === "number" ? "number" : "text"}
                                step={schema.type === "integer" ? 1 : "any"} min={schema.minimum} max={schema.maximum}
                                className={cn(CONTROL_CLASS, "mt-2")} value={String(value ?? "")}
                                aria-invalid={Boolean(fieldErrors[field])}
                                onChange={(event) => {
                                  setDraft((current) => ({ ...current, modelParams: { ...current.modelParams, [key]: event.target.value } }));
                                  clearError(field);
                                }}
                              />
                            )}
                            {schema.description && <p className={HELP_CLASS}>{schema.description}</p>}
                            <FieldError field={field} errors={fieldErrors} />
                          </div>
                        );
                      })}
                      {!Object.keys(modelProperties).length && <p className="col-span-full text-sm text-muted-foreground">No configurable parameters.</p>}
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div>
                      <label className={LABEL_CLASS}>Power epsilon</label>
                      <input
                        type="number" min={0.0001} max={1} step="0.01" className={cn(CONTROL_CLASS, "mt-2")}
                        value={draft.epsilon} aria-invalid={Boolean(fieldErrors.epsilon)}
                        onChange={(event) => {
                          setDraft((current) => ({ ...current, epsilon: event.target.value }));
                          clearError("epsilon");
                        }}
                      />
                      <p className={HELP_CLASS}>Controls p-to-e sensitivity.</p>
                      <FieldError field="epsilon" errors={fieldErrors} />
                    </div>
                    <div>
                      <label className={LABEL_CLASS}>Sensor freshness (s)</label>
                      <input
                        type="number" min={1} className={cn(CONTROL_CLASS, "mt-2")}
                        value={draft.sensorFreshness} aria-invalid={Boolean(fieldErrors.sensorFreshness)}
                        onChange={(event) => {
                          setDraft((current) => ({ ...current, sensorFreshness: event.target.value }));
                          clearError("sensorFreshness");
                        }}
                      />
                      <p className={HELP_CLASS}>Maximum alignment age.</p>
                      <FieldError field="sensorFreshness" errors={fieldErrors} />
                    </div>
                    <div>
                      <label className={LABEL_CLASS}>Sensor identity</label>
                      <select
                        className={cn(CONTROL_CLASS, "mt-2")} value={draft.sensorKeyStrategy}
                        onChange={(event) => setDraft((current) => ({ ...current, sensorKeyStrategy: event.target.value as SensorKeyStrategy }))}
                      >
                        <option value="full_hierarchy">Full hierarchy</option>
                        <option value="top_level">Top level</option>
                        <option value="leaf">Leaf</option>
                      </select>
                      <p className={HELP_CLASS}>How aligned feature names are built.</p>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
              <div className="overflow-hidden rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.055] p-5">
                <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300"><ShieldCheck className="h-5 w-5" /><h3 className="font-semibold">Fixed Ville threshold</h3></div>
                <div className="mt-5 flex items-end justify-between gap-3">
                  <div className="text-5xl font-semibold tracking-[-0.05em] tabular-nums">{FIXED_VILLE_THRESHOLD}</div>
                  <span className="mb-1 rounded-full border border-emerald-500/25 bg-background/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-700 dark:text-emerald-300">Fixed</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">The native restarted mixture fires on a new crossing of 100. It is not manually reset and the threshold is not configurable.</p>
              </div>
              <div className="rounded-2xl border border-border/65 bg-card p-5">
                <div className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-primary" /><h3 className="font-semibold">Assignment summary</h3></div>
                <dl className="mt-4 divide-y divide-border/60 text-sm">
                  <div className="flex justify-between gap-4 py-3 first:pt-0"><dt className="text-muted-foreground">Selected streams</dt><dd className="font-medium tabular-nums">{effectiveTopics.length}</dd></div>
                  <div className="flex justify-between gap-4 py-3"><dt className="text-muted-foreground">Already assigned</dt><dd className="font-medium tabular-nums">{claimsBySensor.size}</dd></div>
                  <div className="flex justify-between gap-4 py-3 last:pb-0"><dt className="text-muted-foreground">Alignment</dt><dd className="font-medium">Strict barrier</dd></div>
                </dl>
              </div>
              <div className="rounded-2xl border border-amber-500/25 bg-amber-500/[0.045] p-5 text-sm leading-6 text-muted-foreground">
                Evidence assumes the static calibration remains representative. Temporal dependence is intentionally deferred to the future dynamic lane.
              </div>
            </aside>
          </div>
        </SectionPanel>

        <SectionPanel
          title="Active services" description="Runtime lifecycle and current stream ownership."
          actions={<Button variant="outline" onClick={loadServices} disabled={loadingServices}><RefreshCw className={cn("h-4 w-4", loadingServices && "animate-spin")} />Refresh</Button>}
          contentClassName="p-0"
        >
          {!services.length ? <p className="m-5 rounded-xl border border-dashed p-5 text-sm text-muted-foreground sm:m-6">No active monitoring services.</p> : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow className="bg-muted/30 hover:bg-muted/30"><TableHead>Service</TableHead><TableHead>Lifecycle</TableHead><TableHead>Runtime</TableHead><TableHead>Topics</TableHead><TableHead className="text-right">Action</TableHead></TableRow></TableHeader>
                <TableBody>
                  {services.map((service) => {
                    const stage = service.operational_status ? getOperationalStageDisplay(service.operational_status) : undefined;
                    const runtime = getStatusDisplay(service.docker_status, service.status);
                    return (
                      <TableRow key={service.id}>
                        <TableCell><div className="font-medium">{service.container_name}</div><div className="text-xs text-muted-foreground">{service.model_type ? humanize(service.model_type) : "Static baseline"}</div></TableCell>
                        <TableCell><span className={cn("rounded-full px-2 py-1 text-xs font-medium", stage?.className ?? "bg-muted text-muted-foreground")}>{stage?.label ?? "Starting"}</span></TableCell>
                        <TableCell><span className={cn("rounded-full px-2 py-1 text-xs font-medium", runtime.className)}>{runtime.label}</span></TableCell>
                        <TableCell className="max-w-xs"><div className="truncate text-xs text-muted-foreground">{(service.mqtt_topics ?? []).join(", ")}</div></TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="icon" aria-label={getServiceDeleteActionDisplay(service).ariaLabel} onClick={() => void deleteService(service)}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </SectionPanel>

        <SectionPanel
          title="Recent alarm transitions"
          description="Only new threshold crossings are anomaly events; the full evidence path is persisted for charts."
          actions={<Button variant="outline" onClick={loadAnomalies} disabled={loadingAnomalies}><RefreshCw className={cn("h-4 w-4", loadingAnomalies && "animate-spin")} />Refresh</Button>}
          contentClassName="p-0"
        >
          {!anomalies.length ? <p className="m-5 rounded-xl border border-dashed p-5 text-sm text-muted-foreground sm:m-6">No recent alarm transitions.</p> : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow className="bg-muted/30 hover:bg-muted/30"><TableHead>Time</TableHead><TableHead>Sensors</TableHead><TableHead>Evidence input</TableHead><TableHead>Type</TableHead></TableRow></TableHeader>
                <TableBody>
                  {anomalies.slice(0, 50).map((anomaly) => (
                    <TableRow key={anomaly.anomaly_id ?? `${anomaly.timestamp}-${anomaly.telemetry_type}`}>
                      <TableCell>{new Date(anomaly.timestamp).toLocaleString()}</TableCell>
                      <TableCell>{formatAnomalySensorSet(anomaly.sensor_set) || anomaly.telemetry_type}</TableCell>
                      <TableCell><div className="font-mono text-xs">{formatAnomalyValue(anomaly.anomaly_value, anomaly.value_type)}</div><div className="text-xs text-muted-foreground">{getAnomalyValueLabel(anomaly.value_type)}</div></TableCell>
                      <TableCell className="capitalize">{anomaly.anomaly_type.replace(/_/g, " ")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </SectionPanel>
      </PageShell>
    </>
  );
};

export default Monitoring;
