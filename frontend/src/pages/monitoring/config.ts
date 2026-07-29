import type {
  ActiveService,
  AnomalyDetectionRequest,
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MartingaleTrackerConfig,
  ModelDefinition,
  ModelParams,
} from "@/types/monitoring";

export type ConfigValue = string | number | boolean;
export type FieldErrors = Record<string, string>;
export type TopicMode = "selected_sensors" | "direct_patterns";
export type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";

export interface MartingaleTrackerDraft {
  trackerId: string;
  bettingFunction: MartingaleBettingFunction;
  alarmStatistic: MartingaleAlarmStatistic;
  threshold: string;
  epsilon: string;
  nGrid: string;
  minEpsilon: string;
  jump: string;
}

export interface StaticDraft {
  modelType: string;
  modelParams: Record<string, ConfigValue>;
  trainingWindow: string;
  calibrationWindow: string;
  martingaleTrackers: MartingaleTrackerDraft[];
  sensorFreshness: string;
  sensorKeyStrategy: SensorKeyStrategy;
}

export const DEFAULT_MODEL_TYPE = "pyod_iforest";
export const DEFAULT_MARTINGALE_THRESHOLD = 100;

export const createDefaultMartingaleTracker = (
  trackerId = "primary",
): MartingaleTrackerDraft => ({
  trackerId,
  bettingFunction: "power",
  alarmStatistic: "restarted_martingale",
  threshold: String(DEFAULT_MARTINGALE_THRESHOLD),
  epsilon: "0.5",
  nGrid: "100",
  minEpsilon: "0.01",
  jump: "0.01",
});

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
  martingaleTrackers: [createDefaultMartingaleTracker()],
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
  const trackerIds = new Set<string>();
  const martingaleTrackers: MartingaleTrackerConfig[] = [];
  draft.martingaleTrackers.forEach((tracker, index) => {
    const prefix = `martingales.${index}`;
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(tracker.trackerId)) {
      errors[`${prefix}.trackerId`] = "Tracker ID is invalid.";
    } else if (trackerIds.has(tracker.trackerId)) {
      errors[`${prefix}.trackerId`] = "Tracker IDs must be unique.";
    }
    trackerIds.add(tracker.trackerId);

    const threshold = parseNumber({
      value: tracker.threshold,
      label: "Alarm threshold",
      field: `${prefix}.threshold`,
      errors,
      min: Number.MIN_VALUE,
    });
    if (
      threshold !== undefined &&
      (tracker.alarmStatistic === "martingale" ||
        tracker.alarmStatistic === "restarted_martingale") &&
      threshold <= 1
    ) {
      errors[`${prefix}.threshold`] = "Ville thresholds must be greater than 1.";
    }

    if (tracker.bettingFunction === "power") {
      const epsilon = parseNumber({
        value: tracker.epsilon,
        label: "Power epsilon",
        field: `${prefix}.epsilon`,
        errors,
        min: 0.0001,
        max: 1,
      });
      if (epsilon !== undefined && threshold !== undefined) {
        martingaleTrackers.push({
          tracker_id: tracker.trackerId,
          betting_function: "power",
          alarm_statistic: tracker.alarmStatistic,
          threshold,
          epsilon,
        });
      }
      return;
    }

    if (tracker.bettingFunction === "simple_mixture") {
      const nGrid = parseNumber({
        value: tracker.nGrid,
        label: "Mixture grid size",
        field: `${prefix}.nGrid`,
        errors,
        integer: true,
        min: 2,
        max: 10000,
      });
      const minEpsilon = parseNumber({
        value: tracker.minEpsilon,
        label: "Minimum epsilon",
        field: `${prefix}.minEpsilon`,
        errors,
        min: 0.0001,
        max: 1,
      });
      if (
        nGrid !== undefined &&
        minEpsilon !== undefined &&
        threshold !== undefined
      ) {
        martingaleTrackers.push({
          tracker_id: tracker.trackerId,
          betting_function: "simple_mixture",
          alarm_statistic: tracker.alarmStatistic,
          threshold,
          n_grid: nGrid,
          min_epsilon: minEpsilon,
        });
      }
      return;
    }

    const jump = parseNumber({
      value: tracker.jump,
      label: "Jumper redistribution",
      field: `${prefix}.jump`,
      errors,
      min: 0.0001,
      max: 1,
    });
    if (jump !== undefined && threshold !== undefined) {
      martingaleTrackers.push({
        tracker_id: tracker.trackerId,
        betting_function: "simple_jumper",
        alarm_statistic: tracker.alarmStatistic,
        threshold,
        jump,
      });
    }
  });
  if (!draft.martingaleTrackers.length) {
    errors.martingales = "Configure at least one martingale tracker.";
  }
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
    martingaleTrackers.length !== draft.martingaleTrackers.length ||
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
          trackers: martingaleTrackers,
        },
      },
    },
  };
};
