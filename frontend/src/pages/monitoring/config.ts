import type {
  MonitoringStartRequest,
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  MartingaleTrackerConfig,
  ModelDefinition,
  ModelParams,
  JsonValue,
  AdaptivePreprocessingStep,
  AdaptiveAnomalyDetectionRequest,
  StaticAnomalyDetectionRequest,
} from "@/types/monitoring";
import { parseDeviceTelemetryTopic } from "@/lib/mqtt-topics";

export {
  buildSensorClaims,
  mqttFiltersOverlap,
} from "@/lib/monitoring-services";

export type ConfigValue = JsonValue;
export type FieldErrors = Record<string, string>;
export type TopicMode = "selected_sensors" | "direct_patterns";
export type SensorKeyStrategy = "full_hierarchy" | "top_level" | "leaf";

export interface MartingaleTrackerDraft {
  trackerId: string;
  bettingFunction: MartingaleBettingFunction;
  alarmStatistic: MartingaleAlarmStatistic;
  thresholdMode: "manual" | "automatic";
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
  automaticFalseAlarmProbability: string;
  automaticThresholdHorizon: string;
  automaticThresholdSimulations: string;
  sensorFreshness: string;
  sensorKeyStrategy: SensorKeyStrategy;
}

export interface AdaptiveDraft {
  modelType: string;
  modelParams: Record<string, ConfigValue>;
  trainingWindow: string;
  calibrationWindow: string;
  thresholdQuantile: string;
  scaler: "none" | "standard_scaler" | "min_max_scaler";
  scalerWithStd: boolean;
  minMaxLower: string;
  minMaxUpper: string;
  projection: "none" | "incremental_pca" | "random_projection";
  projectionComponents: string;
  projectionN0: string;
  projectionTolerance: string;
  projectionForgettingFactor: string;
  projectionSeed: string;
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
  thresholdMode: "manual",
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
  automaticFalseAlarmProbability: "0.01",
  automaticThresholdHorizon: "1000",
  automaticThresholdSimulations: "5000",
  sensorFreshness: "30",
  sensorKeyStrategy: "full_hierarchy",
});

export const createDefaultAdaptiveDraft = (): AdaptiveDraft => ({
  modelType: "aberrant_online_isolation_forest",
  modelParams: {},
  trainingWindow: "1200",
  calibrationWindow: "360",
  thresholdQuantile: "1",
  scaler: "standard_scaler",
  scalerWithStd: true,
  minMaxLower: "0",
  minMaxUpper: "1",
  projection: "none",
  projectionComponents: "2",
  projectionN0: "100",
  projectionTolerance: "0.0000001",
  projectionForgettingFactor: "",
  projectionSeed: "42",
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

export const getModelDefaults = (
  modelType: string,
  definition: ModelDefinition | undefined,
): Record<string, ConfigValue> => {
  const defaults: Record<string, ConfigValue> = {};
  for (const [key, value] of Object.entries(
    definition?.default_parameters ?? {},
  )) {
    defaults[key] = value as JsonValue;
  }
  for (const [key, schema] of Object.entries(
    definition?.parameters?.properties ?? {},
  )) {
    if (
      defaults[key] === undefined &&
      schema.default !== undefined
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
    const schemaType = schema?.type ?? schema?.anyOf?.find((item) => item.type !== "null")?.type;
    if (value === null) cleaned[key] = null;
    else if (schemaType === "boolean") cleaned[key] = Boolean(value);
    else if (value === "" || value === undefined) {
      if (required.has(key)) errors[field] = `${humanize(key)} is required.`;
    } else if (schemaType === "integer" || schemaType === "number") {
      const parsed = parseNumber({
        value,
        label: humanize(key),
        field,
        errors,
        integer: schemaType === "integer",
        min: schema?.minimum,
        max: schema?.maximum,
      });
      if (parsed !== undefined) cleaned[key] = parsed;
    } else if (schemaType === "array" || schemaType === "object") {
      if (typeof value !== "string") cleaned[key] = value;
      else {
        try {
          const parsed = JSON.parse(value) as JsonValue;
          if (
            (schemaType === "array" && !Array.isArray(parsed)) ||
            (schemaType === "object" &&
              (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)))
          ) {
            errors[field] = `${humanize(key)} must be a JSON ${schemaType}.`;
          } else cleaned[key] = parsed;
        } catch {
          errors[field] = `${humanize(key)} must contain valid JSON.`;
        }
      }
    } else cleaned[key] = value;
  }
  return cleaned;
};

export const buildAdaptiveMonitoringRequest = ({
  chargerId,
  topics,
  draft,
  modelDefinition,
  containerName,
}: {
  chargerId: string;
  topics: string[];
  draft: AdaptiveDraft;
  modelDefinition: ModelDefinition | undefined;
  containerName: string;
}): RequestValidation<AdaptiveAnomalyDetectionRequest> => {
  const errors: FieldErrors = {};
  if (!topics.length) errors.topics = "Select at least one unassigned sensor.";
  else if (topics.some((topic) => topic.split("/").some((part) => part === "+" || part === "#"))) {
    errors.topics = "Adaptive monitoring requires concrete sensor topics.";
  } else if (topics.some((topic) => parseDeviceTelemetryTopic(topic) === null)) {
    errors.topics =
      "Sensor topics must use device/evCharger/<charger_id>/<telemetry_type>.";
  } else if (
    topics.some(
      (topic) => parseDeviceTelemetryTopic(topic)?.chargerId !== chargerId,
    )
  ) {
    errors.topics = `All sensor topics must belong to charger ${chargerId}.`;
  }
  const trainingWindow = parseNumber({
    value: draft.trainingWindow, label: "Warm-up samples", field: "trainingWindow",
    errors, integer: true, min: 1,
  });
  const calibrationWindow = parseNumber({
    value: draft.calibrationWindow, label: "Calibration samples",
    field: "calibrationWindow", errors, integer: true, min: 1,
  });
  const quantile = parseNumber({
    value: draft.thresholdQuantile, label: "Threshold quantile",
    field: "thresholdQuantile", errors, min: Number.MIN_VALUE, max: 1,
  });
  const sensorFreshness = parseNumber({
    value: draft.sensorFreshness, label: "Sensor freshness",
    field: "sensorFreshness", errors, min: 1,
  });
  const preprocessingSteps: AdaptivePreprocessingStep[] = [];
  if (draft.scaler === "standard_scaler") {
    preprocessingSteps.push({ type: "standard_scaler", with_std: draft.scalerWithStd });
  } else if (draft.scaler === "min_max_scaler") {
    const lower = parseNumber({
      value: draft.minMaxLower, label: "Minimum scaled value",
      field: "minMaxLower", errors,
    });
    const upper = parseNumber({
      value: draft.minMaxUpper, label: "Maximum scaled value",
      field: "minMaxUpper", errors,
    });
    if (lower !== undefined && upper !== undefined) {
      if (lower >= upper) errors.minMaxUpper = "Maximum scaled value must exceed the minimum.";
      preprocessingSteps.push({ type: "min_max_scaler", feature_range: [lower, upper] });
    }
  }
  if (draft.projection !== "none") {
    const nComponents = parseNumber({
      value: draft.projectionComponents, label: "Projection components",
      field: "projectionComponents", errors, integer: true, min: 1,
    });
    if (nComponents !== undefined && nComponents > topics.length) {
      errors.projectionComponents = "Projection components cannot exceed selected sensors.";
    }
    if (draft.projection === "incremental_pca") {
      const n0 = parseNumber({
        value: draft.projectionN0, label: "PCA initialization samples",
        field: "projectionN0", errors, integer: true, min: 2,
      });
      const tol = parseNumber({
        value: draft.projectionTolerance, label: "PCA tolerance",
        field: "projectionTolerance", errors, min: Number.MIN_VALUE,
      });
      const forgettingFactor = draft.projectionForgettingFactor.trim() === ""
        ? null
        : parseNumber({
            value: draft.projectionForgettingFactor,
            label: "PCA forgetting factor",
            field: "projectionForgettingFactor",
            errors,
            min: Number.MIN_VALUE,
            max: 0.999999,
          });
      if (nComponents !== undefined && n0 !== undefined && tol !== undefined && forgettingFactor !== undefined) {
        if (n0 < nComponents) errors.projectionN0 = "PCA initialization must cover every component.";
        if (trainingWindow !== undefined && n0 > trainingWindow) {
          errors.projectionN0 = "PCA initialization must fit inside the warm-up window.";
        }
        preprocessingSteps.push({
          type: "incremental_pca",
          n_components: nComponents,
          n0,
          tol,
          forgetting_factor: forgettingFactor,
        });
      }
    } else if (nComponents !== undefined) {
      const seed = draft.projectionSeed.trim() === "" ? null : parseNumber({
        value: draft.projectionSeed, label: "Projection seed", field: "projectionSeed",
        errors, integer: true,
      });
      if (seed !== undefined || draft.projectionSeed.trim() === "") {
        preprocessingSteps.push({ type: "random_projection", n_components: nComponents, seed: seed ?? null });
      }
    }
  }
  const modelParams = coerceModelParams(draft.modelParams, modelDefinition, errors);
  if (Object.keys(errors).length || trainingWindow === undefined || calibrationWindow === undefined || quantile === undefined || sensorFreshness === undefined) {
    return { errors };
  }
  return {
    errors,
    request: {
      container_name: containerName,
      service_type: "radar",
      mqtt_topics: topics,
      strategy: "adaptive_stream",
      model_type: draft.modelType,
      model_params: modelParams,
      performance_config: {
        sensor_key_strategy: draft.sensorKeyStrategy,
        sensor_freshness_seconds: sensorFreshness,
      },
      adaptive_stream_config: {
        model_type: draft.modelType,
        model_params: modelParams,
        training_window_size: trainingWindow,
        calibration_window_size: calibrationWindow,
        preprocessing_steps: preprocessingSteps,
        threshold_config: { mode: "calibrated_quantile", quantile },
      },
    },
  };
};

export type RequestValidation<T extends MonitoringStartRequest = MonitoringStartRequest> =
  | { request: T; errors: FieldErrors }
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
}): RequestValidation<StaticAnomalyDetectionRequest> => {
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
  } else if (topics.some((topic) => parseDeviceTelemetryTopic(topic) === null)) {
    errors.topics =
      "Sensor topics must use device/evCharger/<charger_id>/<telemetry_type>.";
  } else if (
    topics.some(
      (topic) => parseDeviceTelemetryTopic(topic)?.chargerId !== chargerId,
    )
  ) {
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
  const automaticTrackerCount = draft.martingaleTrackers.filter(
    (tracker) => tracker.thresholdMode === "automatic",
  ).length;
  const automaticFalseAlarmProbability = parseNumber({
    value: draft.automaticFalseAlarmProbability,
    label: "Automatic false-alarm probability",
    field: "automaticFalseAlarmProbability",
    errors,
    min: Number.MIN_VALUE,
    max: 0.999999,
  });
  const automaticThresholdHorizon = parseNumber({
    value: draft.automaticThresholdHorizon,
    label: "Automatic calibration horizon",
    field: "automaticThresholdHorizon",
    errors,
    integer: true,
    min: 10,
    max: 100000,
  });
  const automaticThresholdSimulations = parseNumber({
    value: draft.automaticThresholdSimulations,
    label: "Automatic calibration simulations",
    field: "automaticThresholdSimulations",
    errors,
    integer: true,
    min: 100,
    max: 100000,
  });
  if (
    automaticThresholdHorizon !== undefined &&
    automaticThresholdSimulations !== undefined &&
    automaticThresholdHorizon * automaticThresholdSimulations > 25_000_000
  ) {
    errors.automaticThresholdSimulations =
      "Horizon times simulations must not exceed 25,000,000.";
  }
  if (
    automaticTrackerCount > 0 &&
    automaticFalseAlarmProbability !== undefined &&
    automaticThresholdSimulations !== undefined
  ) {
    const requiredSimulations =
      Math.ceil(automaticTrackerCount / automaticFalseAlarmProbability) - 1;
    if (automaticThresholdSimulations < requiredSimulations) {
      errors.automaticThresholdSimulations =
        `Use at least ${requiredSimulations.toLocaleString()} simulations for ` +
        `${automaticTrackerCount} automatic tracker${automaticTrackerCount === 1 ? "" : "s"} ` +
        "at this false-alarm probability.";
    }
  }
  draft.martingaleTrackers.forEach((tracker, index) => {
    const prefix = `martingales.${index}`;
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(tracker.trackerId)) {
      errors[`${prefix}.trackerId`] = "Tracker ID is invalid.";
    } else if (trackerIds.has(tracker.trackerId)) {
      errors[`${prefix}.trackerId`] = "Tracker IDs must be unique.";
    }
    trackerIds.add(tracker.trackerId);

    const automaticThreshold = tracker.thresholdMode === "automatic";
    if (
      automaticThreshold &&
      tracker.alarmStatistic !== "cusum" &&
      tracker.alarmStatistic !== "shiryaev_roberts"
    ) {
      errors[`${prefix}.thresholdMode`] =
        "Automatic thresholds are only available for CUSUM and Shiryaev-Roberts.";
    }
    const threshold = automaticThreshold
      ? undefined
      : parseNumber({
          value: tracker.threshold,
          label: "Alarm threshold",
          field: `${prefix}.threshold`,
          errors,
          min: Number.MIN_VALUE,
        });
    if (
      !automaticThreshold &&
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
      if (epsilon !== undefined && (automaticThreshold || threshold !== undefined)) {
        martingaleTrackers.push({
          tracker_id: tracker.trackerId,
          betting_function: "power",
          alarm_statistic: tracker.alarmStatistic,
          threshold_config: automaticThreshold
            ? { mode: "automatic" }
            : { mode: "manual", value: threshold! },
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
        (automaticThreshold || threshold !== undefined)
      ) {
        martingaleTrackers.push({
          tracker_id: tracker.trackerId,
          betting_function: "simple_mixture",
          alarm_statistic: tracker.alarmStatistic,
          threshold_config: automaticThreshold
            ? { mode: "automatic" }
            : { mode: "manual", value: threshold! },
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
    if (jump !== undefined && (automaticThreshold || threshold !== undefined)) {
      martingaleTrackers.push({
        tracker_id: tracker.trackerId,
        betting_function: "simple_jumper",
        alarm_statistic: tracker.alarmStatistic,
        threshold_config: automaticThreshold
          ? { mode: "automatic" }
          : { mode: "manual", value: threshold! },
        jump,
      });
    }
  });
  if (
    automaticThresholdHorizon !== undefined &&
    automaticThresholdSimulations !== undefined
  ) {
    const automaticBettingWidth = martingaleTrackers.reduce(
      (total, tracker) => {
        if (tracker.threshold_config.mode !== "automatic") return total;
        if (tracker.betting_function === "simple_mixture") {
          return total + tracker.n_grid;
        }
        return total + (tracker.betting_function === "simple_jumper" ? 3 : 1);
      },
      0,
    );
    if (
      automaticThresholdHorizon *
        automaticThresholdSimulations *
        automaticBettingWidth >
      1_000_000_000
    ) {
      errors.automaticThresholdSimulations =
        "Automatic calibration is too large; reduce the horizon, simulations, " +
        "automatic trackers, or mixture grid size.";
    }
  }
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
    sensorFreshness === undefined ||
    automaticFalseAlarmProbability === undefined ||
    automaticThresholdHorizon === undefined ||
    automaticThresholdSimulations === undefined
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
          automatic_threshold_calibration: {
            false_alarm_probability: automaticFalseAlarmProbability,
            horizon: automaticThresholdHorizon,
            simulation_count: automaticThresholdSimulations,
          },
        },
      },
    },
  };
};
