import type {
  ActiveService,
  AnomalyDetectionRequest,
  ModelDefinition,
  ModelParams,
} from "@/types/monitoring";

export type ConfigValue = string | number | boolean;
export type FieldErrors = Record<string, string>;
export type TopicMode = "selected_sensors" | "direct_patterns";
export type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";

export interface StaticDraft {
  modelType: string;
  modelParams: Record<string, ConfigValue>;
  trainingWindow: string;
  calibrationWindow: string;
  epsilon: string;
  sensorFreshness: string;
  sensorKeyStrategy: SensorKeyStrategy;
}

export const DEFAULT_MODEL_TYPE = "pyod_iforest";
export const FIXED_VILLE_THRESHOLD = 100;

const DEFAULT_MODEL_PARAMS: Record<string, ConfigValue> = {
  n_estimators: 100,
  contamination: 0.1,
  random_state: 42,
};

export const createDefaultStaticDraft = (): StaticDraft => ({
  modelType: DEFAULT_MODEL_TYPE,
  modelParams: { ...DEFAULT_MODEL_PARAMS },
  trainingWindow: "1200",
  calibrationWindow: "360",
  epsilon: "0.5",
  sensorFreshness: "30",
  sensorKeyStrategy: "full_hierarchy",
});

export const parseTopicPatterns = (raw: string): string[] =>
  raw
    .split(/[\n,]/)
    .map((topic) => topic.trim())
    .filter(Boolean);

export const humanize = (value: string): string =>
  value
    .replace(/^pyod_/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

export const mqttFiltersOverlap = (left: string, right: string): boolean => {
  const leftParts = left.trim().split("/");
  const rightParts = right.trim().split("/");
  let index = 0;
  while (index < leftParts.length && index < rightParts.length) {
    if (leftParts[index] === "#" || rightParts[index] === "#") return true;
    if (
      leftParts[index] !== "+" &&
      rightParts[index] !== "+" &&
      leftParts[index] !== rightParts[index]
    ) {
      return false;
    }
    index += 1;
  }
  if (index === leftParts.length && index === rightParts.length) return true;
  if (index < leftParts.length) {
    return index === leftParts.length - 1 && leftParts[index] === "#";
  }
  return index === rightParts.length - 1 && rightParts[index] === "#";
};

export const buildSensorClaims = (
  chargerId: string,
  sensorTypes: string[],
  services: ActiveService[],
): Map<string, ActiveService> => {
  const claims = new Map<string, ActiveService>();
  for (const sensor of sensorTypes) {
    const concreteTopic = `charger/${chargerId}/live-telemetry/${sensor}`;
    const owner = services.find((service) =>
      (service.mqtt_topics ?? []).some((topic) =>
        mqttFiltersOverlap(topic, concreteTopic),
      ),
    );
    if (owner) claims.set(sensor, owner);
  }
  return claims;
};

export const getModelDefaults = (
  modelType: string,
  definition: ModelDefinition | undefined,
): Record<string, ConfigValue> => {
  const defaults: Record<string, ConfigValue> = {};
  for (const [key, value] of Object.entries(
    definition?.default_parameters ?? {},
  )) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      defaults[key] = value;
    }
  }
  for (const [key, schema] of Object.entries(
    definition?.parameters?.properties ?? {},
  )) {
    if (
      defaults[key] === undefined &&
      (typeof schema.default === "string" ||
        typeof schema.default === "number" ||
        typeof schema.default === "boolean")
    ) {
      defaults[key] = schema.default;
    }
  }
  return modelType === DEFAULT_MODEL_TYPE
    ? { ...defaults, ...DEFAULT_MODEL_PARAMS }
    : defaults;
};

interface NumberField {
  value: ConfigValue | undefined;
  label: string;
  field: string;
  errors: FieldErrors;
  integer?: boolean;
  min?: number;
  max?: number;
}

const parseNumber = ({
  value,
  label,
  field,
  errors,
  integer = false,
  min,
  max,
}: NumberField): number | undefined => {
  const raw = String(value ?? "").trim();
  if (!raw) {
    errors[field] = `${label} is required.`;
    return undefined;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) errors[field] = `${label} must be a number.`;
  else if (integer && !Number.isInteger(parsed)) {
    errors[field] = `${label} must be an integer.`;
  } else if (min !== undefined && parsed < min) {
    errors[field] = `${label} must be at least ${min}.`;
  } else if (max !== undefined && parsed > max) {
    errors[field] = `${label} must be at most ${max}.`;
  } else return parsed;
  return undefined;
};

const coerceModelParams = (
  params: Record<string, ConfigValue>,
  definition: ModelDefinition | undefined,
  errors: FieldErrors,
): ModelParams => {
  const cleaned: ModelParams = {};
  const properties = definition?.parameters?.properties ?? {};
  const required = new Set(definition?.parameters?.required ?? []);
  for (const key of new Set([...Object.keys(params), ...required])) {
    const schema = properties[key];
    const value = params[key];
    const field = `model.${key}`;
    if (schema?.type === "boolean") cleaned[key] = Boolean(value);
    else if (value === "" || value === undefined) {
      if (required.has(key)) errors[field] = `${humanize(key)} is required.`;
    } else if (schema?.type === "integer" || schema?.type === "number") {
      const parsed = parseNumber({
        value,
        label: humanize(key),
        field,
        errors,
        integer: schema.type === "integer",
        min: schema.minimum,
        max: schema.maximum,
      });
      if (parsed !== undefined) cleaned[key] = parsed;
    } else cleaned[key] = value;
  }
  return cleaned;
};

export type RequestValidation =
  | { request: AnomalyDetectionRequest; errors: FieldErrors }
  | { request?: never; errors: FieldErrors };

export const buildStaticMonitoringRequest = ({
  chargerId,
  topics,
  draft,
  modelDefinition,
  containerName,
}: {
  chargerId: string;
  topics: string[];
  draft: StaticDraft;
  modelDefinition: ModelDefinition | undefined;
  containerName: string;
}): RequestValidation => {
  const errors: FieldErrors = {};
  if (!topics.length) {
    errors.topics = "Select at least one unassigned sensor or enter a topic.";
  } else if (
    topics.some((topic) =>
      topic.split("/").some((part) => part === "+" || part === "#"),
    )
  ) {
    errors.topics =
      "Static monitoring requires concrete sensor topics without MQTT wildcards.";
  } else if (topics.some((topic) => topic.split("/")[1] !== chargerId)) {
    errors.topics = `All sensor topics must belong to charger ${chargerId}.`;
  }

  const trainingWindow = parseNumber({
    value: draft.trainingWindow,
    label: "Training samples",
    field: "trainingWindow",
    errors,
    integer: true,
    min: 20,
  });
  const calibrationWindow = parseNumber({
    value: draft.calibrationWindow,
    label: "Calibration samples",
    field: "calibrationWindow",
    errors,
    integer: true,
    min: 1,
  });
  const epsilon = parseNumber({
    value: draft.epsilon,
    label: "Power epsilon",
    field: "epsilon",
    errors,
    min: 0.0001,
    max: 1,
  });
  const sensorFreshness = parseNumber({
    value: draft.sensorFreshness,
    label: "Sensor freshness",
    field: "sensorFreshness",
    errors,
    min: 1,
  });
  const modelParams = coerceModelParams(
    draft.modelParams,
    modelDefinition,
    errors,
  );

  if (
    Object.keys(errors).length ||
    trainingWindow === undefined ||
    calibrationWindow === undefined ||
    epsilon === undefined ||
    sensorFreshness === undefined
  ) {
    return { errors };
  }

  return {
    errors,
    request: {
      container_name: containerName,
      service_type: "radar",
      mqtt_topics: topics,
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
  };
};
