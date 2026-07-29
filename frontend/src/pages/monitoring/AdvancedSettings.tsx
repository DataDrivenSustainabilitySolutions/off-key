import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  MartingaleAlarmStatistic,
  MartingaleBettingFunction,
  ParameterSchema,
} from "@/types/monitoring";
import { ChevronDown, Plus, Settings2, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { useState } from "react";

import { createDefaultMartingaleTracker, humanize } from "./config";
import type {
  FieldErrors,
  SensorKeyStrategy,
  StaticDraft,
} from "./config";
import {
  CONTROL_CLASS,
  HELP_CLASS,
} from "./formStyles";
import { FieldError } from "./MonitoringUi";
import { SettingInfo, SettingLabel } from "./SettingInfo";

const BETTING_METHOD_HELP =
  "Transforms each conformal p-value into a one-step e-value. Power uses one epsilon, Simple mixture averages a grid of power bets, and Simple jumper redistributes capital between component bettors.";
const ALARM_STATISTIC_HELP =
  "Selects the sequential value compared with the threshold: the all-history e-process, harmonic restarted e-process, CUSUM, or Shiryaev–Roberts statistic.";
const TRACKER_ID_HELP =
  "A unique, stable identifier stored with evidence and used to identify this series in charts and APIs.";

const describeDetectorParameter = (schema: ParameterSchema): string => {
  const details = [
    schema.description ?? "A model-specific parameter used to fit the detector.",
    `Expected type: ${schema.type}.`,
  ];
  if (schema.enum?.length) {
    details.push(`Allowed values: ${schema.enum.join(", ")}.`);
  } else if (schema.minimum !== undefined || schema.maximum !== undefined) {
    details.push(
      `Allowed range: ${schema.minimum ?? "unbounded"} to ${schema.maximum ?? "unbounded"}.`,
    );
  }
  return details.join(" ");
};

const thresholdHelp = (statistic: MartingaleAlarmStatistic): string =>
  statistic === "martingale" || statistic === "restarted_martingale"
    ? "Emits an alarm on a new upward crossing. This Ville-style threshold must be greater than 1; larger values require stronger evidence."
    : "Emits an alarm on a new upward crossing. Calibrate this CUSUM or Shiryaev–Roberts threshold empirically; it is not a Ville error-probability bound.";

const normalizeSensorKeyStrategy = (value: string): SensorKeyStrategy => {
  if (value === "top_level" || value === "leaf") return value;
  return "full_hierarchy";
};

const normalizeBettingFunction = (value: string): MartingaleBettingFunction => {
  if (value === "simple_mixture" || value === "simple_jumper") return value;
  return "power";
};

const normalizeAlarmStatistic = (value: string): MartingaleAlarmStatistic => {
  if (
    value === "martingale" ||
    value === "cusum" ||
    value === "shiryaev_roberts"
  ) return value;
  return "restarted_martingale";
};

interface AdvancedSettingsProps {
  draft: StaticDraft;
  modelProperties: Record<string, ParameterSchema>;
  fieldErrors: FieldErrors;
  setDraft: Dispatch<SetStateAction<StaticDraft>>;
  clearError: (field: string) => void;
}

export function AdvancedSettings({
  draft,
  modelProperties,
  fieldErrors,
  setDraft,
  clearError,
}: AdvancedSettingsProps) {
  const [expanded, setExpanded] = useState(false);
  const updateTracker = (
    index: number,
    changes: Partial<StaticDraft["martingaleTrackers"][number]>,
  ) => {
    setDraft((current) => ({
      ...current,
      martingaleTrackers: current.martingaleTrackers.map((tracker, itemIndex) =>
        itemIndex === index ? { ...tracker, ...changes } : tracker,
      ),
    }));
  };

  const addTracker = () => {
    setDraft((current) => {
      const usedIds = new Set(
        current.martingaleTrackers.map((tracker) => tracker.trackerId),
      );
      let suffix = current.martingaleTrackers.length + 1;
      while (usedIds.has(`tracker-${suffix}`)) suffix += 1;
      return {
        ...current,
        martingaleTrackers: [
          ...current.martingaleTrackers,
          createDefaultMartingaleTracker(`tracker-${suffix}`),
        ],
      };
    });
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        className="w-full justify-between"
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          {expanded ? "Hide advanced settings" : "Show advanced settings"}
        </span>
        <ChevronDown
          className={cn(
            "size-4 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </Button>

      {expanded && (
        <div className="space-y-6 rounded-2xl border border-border/65 bg-muted/[0.16] p-5 sm:p-6">
          <div>
            <div className="flex items-center gap-1">
              <h3 className="font-semibold">Detector parameters</h3>
              <SettingInfo label="Detector parameters">
                These model-specific values control how the baseline detector is
                fitted and scored. Their allowed types and ranges come from the
                selected model registry entry.
              </SettingInfo>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {Object.entries(modelProperties).map(([key, schema]) => {
                const field = `model.${key}`;
                const value = draft.modelParams[key];
                const controlId = `advanced-model-${key}`;
                return (
                  <div key={key}>
                    <SettingLabel
                      label={humanize(key)}
                      help={describeDetectorParameter(schema)}
                      htmlFor={controlId}
                    />
                    {schema.enum ? (
                      <select
                        id={controlId}
                        className={cn(CONTROL_CLASS, "mt-2")}
                        value={String(value ?? "")}
                        onChange={(event) => {
                          setDraft((current) => ({
                            ...current,
                            modelParams: {
                              ...current.modelParams,
                              [key]: event.target.value,
                            },
                          }));
                          clearError(field);
                        }}
                      >
                        {schema.enum.map((option) => (
                          <option key={String(option)} value={String(option)}>
                            {humanize(String(option))}
                          </option>
                        ))}
                      </select>
                    ) : schema.type === "boolean" ? (
                      <label className="mt-3 flex items-center gap-2 text-sm">
                        <input
                          id={controlId}
                          type="checkbox"
                          className="size-4 accent-primary"
                          checked={Boolean(value)}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              modelParams: {
                                ...current.modelParams,
                                [key]: event.target.checked,
                              },
                            }));
                            clearError(field);
                          }}
                        />
                        Enabled
                      </label>
                    ) : (
                      <input
                        id={controlId}
                        type={
                          schema.type === "integer" || schema.type === "number"
                            ? "number"
                            : "text"
                        }
                        step={schema.type === "integer" ? 1 : "any"}
                        min={schema.minimum}
                        max={schema.maximum}
                        className={cn(CONTROL_CLASS, "mt-2")}
                        value={String(value ?? "")}
                        aria-invalid={Boolean(fieldErrors[field])}
                        onChange={(event) => {
                          setDraft((current) => ({
                            ...current,
                            modelParams: {
                              ...current.modelParams,
                              [key]: event.target.value,
                            },
                          }));
                          clearError(field);
                        }}
                      />
                    )}
                    {schema.description && (
                      <p className={HELP_CLASS}>{schema.description}</p>
                    )}
                    <FieldError field={field} errors={fieldErrors} />
                  </div>
                );
              })}
              {!Object.keys(modelProperties).length && (
                <p className="col-span-full text-sm text-muted-foreground">
                  No configurable parameters.
                </p>
              )}
            </div>
          </div>
          <div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-1">
                  <h3 className="font-semibold">Martingale trackers</h3>
                  <SettingInfo label="Martingale trackers">
                    Every tracker receives the same ordered p-value stream. Each
                    tracker may use a different betting method, statistic, and
                    threshold; any new crossing emits an anomaly.
                  </SettingInfo>
                </div>
                <p className={HELP_CLASS}>
                  Every tracker receives the same ordered conformal p-values.
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={draft.martingaleTrackers.length >= 16}
                onClick={addTracker}
              >
                <Plus className="size-4" />
                Add tracker
              </Button>
            </div>
            <FieldError field="martingales" errors={fieldErrors} />
            <div className="mt-4 space-y-4">
              {draft.martingaleTrackers.map((tracker, index) => {
                const prefix = `martingales.${index}`;
                const controlPrefix = `martingale-tracker-${index}`;
                return (
                  <div
                    key={`${tracker.trackerId}-${index}`}
                    className="rounded-xl border border-border/70 bg-background/65 p-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <h4 className="font-medium">Tracker {index + 1}</h4>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove tracker ${index + 1}`}
                        disabled={draft.martingaleTrackers.length === 1}
                        onClick={() =>
                          setDraft((current) => ({
                            ...current,
                            martingaleTrackers: current.martingaleTrackers.filter(
                              (_, itemIndex) => itemIndex !== index,
                            ),
                          }))
                        }
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <SettingLabel
                          label="Tracker ID"
                          help={TRACKER_ID_HELP}
                          htmlFor={`${controlPrefix}-id`}
                        />
                        <input
                          id={`${controlPrefix}-id`}
                          className={cn(CONTROL_CLASS, "mt-2")}
                          value={tracker.trackerId}
                          aria-invalid={Boolean(fieldErrors[`${prefix}.trackerId`])}
                          onChange={(event) => {
                            updateTracker(index, { trackerId: event.target.value });
                            clearError(`${prefix}.trackerId`);
                          }}
                        />
                        <FieldError field={`${prefix}.trackerId`} errors={fieldErrors} />
                      </div>
                      <div>
                        <SettingLabel
                          label="Betting method"
                          help={BETTING_METHOD_HELP}
                          htmlFor={`${controlPrefix}-betting-method`}
                        />
                        <select
                          id={`${controlPrefix}-betting-method`}
                          className={cn(CONTROL_CLASS, "mt-2")}
                          value={tracker.bettingFunction}
                          onChange={(event) =>
                            updateTracker(index, {
                              bettingFunction: normalizeBettingFunction(
                                event.target.value,
                              ),
                            })
                          }
                        >
                          <option value="power">Power</option>
                          <option value="simple_mixture">Simple mixture</option>
                          <option value="simple_jumper">Simple jumper</option>
                        </select>
                      </div>
                      <div>
                        <SettingLabel
                          label="Alarm statistic"
                          help={ALARM_STATISTIC_HELP}
                          htmlFor={`${controlPrefix}-alarm-statistic`}
                        />
                        <select
                          id={`${controlPrefix}-alarm-statistic`}
                          className={cn(CONTROL_CLASS, "mt-2")}
                          value={tracker.alarmStatistic}
                          onChange={(event) =>
                            updateTracker(index, {
                              alarmStatistic: normalizeAlarmStatistic(
                                event.target.value,
                              ),
                            })
                          }
                        >
                          <option value="martingale">All-history martingale</option>
                          <option value="restarted_martingale">Restarted mixture</option>
                          <option value="cusum">CUSUM</option>
                          <option value="shiryaev_roberts">Shiryaev-Roberts</option>
                        </select>
                      </div>
                      <div>
                        <SettingLabel
                          label="Alarm threshold"
                          help={thresholdHelp(tracker.alarmStatistic)}
                          htmlFor={`${controlPrefix}-threshold`}
                        />
                        <input
                          id={`${controlPrefix}-threshold`}
                          type="number"
                          min={tracker.alarmStatistic.includes("martingale") ? 1.0001 : 0.0001}
                          step="any"
                          className={cn(CONTROL_CLASS, "mt-2")}
                          value={tracker.threshold}
                          aria-invalid={Boolean(fieldErrors[`${prefix}.threshold`])}
                          onChange={(event) => {
                            updateTracker(index, { threshold: event.target.value });
                            clearError(`${prefix}.threshold`);
                          }}
                        />
                        <FieldError field={`${prefix}.threshold`} errors={fieldErrors} />
                      </div>
                      {tracker.bettingFunction === "power" && (
                        <div>
                          <SettingLabel
                            label="Power epsilon"
                            help="The parameter in the power betting function εp^(ε−1). It must be greater than 0 and at most 1; tune it for the p-value alternatives you expect."
                            htmlFor={`${controlPrefix}-epsilon`}
                          />
                          <input
                            id={`${controlPrefix}-epsilon`}
                            type="number"
                            min={0.0001}
                            max={1}
                            step="0.01"
                            className={cn(CONTROL_CLASS, "mt-2")}
                            value={tracker.epsilon}
                            aria-invalid={Boolean(fieldErrors[`${prefix}.epsilon`])}
                            onChange={(event) => {
                              updateTracker(index, { epsilon: event.target.value });
                              clearError(`${prefix}.epsilon`);
                            }}
                          />
                          <FieldError field={`${prefix}.epsilon`} errors={fieldErrors} />
                        </div>
                      )}
                      {tracker.bettingFunction === "simple_mixture" && (
                        <>
                          <div>
                            <SettingLabel
                              label="Grid size"
                              help="Number of power-bet epsilon values averaged by the simple mixture. A larger grid gives finer numerical coverage but costs more computation per sample."
                              htmlFor={`${controlPrefix}-grid-size`}
                            />
                            <input
                              id={`${controlPrefix}-grid-size`}
                              type="number"
                              min={2}
                              max={10000}
                              step={1}
                              className={cn(CONTROL_CLASS, "mt-2")}
                              value={tracker.nGrid}
                              onChange={(event) => {
                                updateTracker(index, { nGrid: event.target.value });
                                clearError(`${prefix}.nGrid`);
                              }}
                            />
                            <FieldError field={`${prefix}.nGrid`} errors={fieldErrors} />
                          </div>
                          <div>
                            <SettingLabel
                              label="Minimum epsilon"
                              help="Lower endpoint of the mixture's epsilon grid. It must be greater than 0 and at most 1."
                              htmlFor={`${controlPrefix}-minimum-epsilon`}
                            />
                            <input
                              id={`${controlPrefix}-minimum-epsilon`}
                              type="number"
                              min={0.0001}
                              max={1}
                              step="0.01"
                              className={cn(CONTROL_CLASS, "mt-2")}
                              value={tracker.minEpsilon}
                              onChange={(event) => {
                                updateTracker(index, { minEpsilon: event.target.value });
                                clearError(`${prefix}.minEpsilon`);
                              }}
                            />
                            <FieldError field={`${prefix}.minEpsilon`} errors={fieldErrors} />
                          </div>
                        </>
                      )}
                      {tracker.bettingFunction === "simple_jumper" && (
                        <div>
                          <SettingLabel
                            label="Redistribution jump"
                            help="Controls how much capital the simple-jumper method redistributes between its component bettors at each observation."
                            htmlFor={`${controlPrefix}-jump`}
                          />
                          <input
                            id={`${controlPrefix}-jump`}
                            type="number"
                            min={0.0001}
                            max={1}
                            step="0.01"
                            className={cn(CONTROL_CLASS, "mt-2")}
                            value={tracker.jump}
                            onChange={(event) => {
                              updateTracker(index, { jump: event.target.value });
                              clearError(`${prefix}.jump`);
                            }}
                          />
                          <FieldError field={`${prefix}.jump`} errors={fieldErrors} />
                        </div>
                      )}
                    </div>
                    {(tracker.alarmStatistic === "cusum" ||
                      tracker.alarmStatistic === "shiryaev_roberts") && (
                      <p className="mt-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
                        Calibrate this change-detection threshold empirically; it is
                        not a Ville error-probability bound.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <SettingLabel
                label="Sensor freshness (s)"
                help="Maximum receive-time age allowed for every required sensor in a strict multivariate alignment. An older sensor blocks inference until it updates."
                htmlFor="advanced-sensor-freshness"
              />
              <input
                id="advanced-sensor-freshness"
                type="number"
                min={1}
                className={cn(CONTROL_CLASS, "mt-2")}
                value={draft.sensorFreshness}
                aria-invalid={Boolean(fieldErrors.sensorFreshness)}
                onChange={(event) => {
                  setDraft((current) => ({
                    ...current,
                    sensorFreshness: event.target.value,
                  }));
                  clearError("sensorFreshness");
                }}
              />
              <p className={HELP_CLASS}>Maximum alignment age.</p>
              <FieldError field="sensorFreshness" errors={fieldErrors} />
            </div>
            <div>
              <SettingLabel
                label="Sensor identity"
                help="Controls feature names derived from MQTT topics. Full hierarchy avoids collisions; top level or leaf can intentionally group shallower topic segments."
                htmlFor="advanced-sensor-identity"
              />
              <select
                id="advanced-sensor-identity"
                className={cn(CONTROL_CLASS, "mt-2")}
                value={draft.sensorKeyStrategy}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    sensorKeyStrategy: normalizeSensorKeyStrategy(
                      event.target.value,
                    ),
                  }))
                }
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
    </>
  );
}
