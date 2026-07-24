import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ParameterSchema } from "@/types/monitoring";
import { ChevronDown, Settings2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { useState } from "react";

import { humanize } from "./config";
import type {
  FieldErrors,
  SensorKeyStrategy,
  StaticDraft,
} from "./config";
import {
  CONTROL_CLASS,
  HELP_CLASS,
  LABEL_CLASS,
} from "./formStyles";
import { FieldError } from "./MonitoringUi";

const normalizeSensorKeyStrategy = (value: string): SensorKeyStrategy => {
  if (value === "top_level" || value === "leaf") return value;
  return "full_hierarchy";
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
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className={LABEL_CLASS}>Power epsilon</label>
              <input
                type="number"
                min={0.0001}
                max={1}
                step="0.01"
                className={cn(CONTROL_CLASS, "mt-2")}
                value={draft.epsilon}
                aria-invalid={Boolean(fieldErrors.epsilon)}
                onChange={(event) => {
                  setDraft((current) => ({
                    ...current,
                    epsilon: event.target.value,
                  }));
                  clearError("epsilon");
                }}
              />
              <p className={HELP_CLASS}>Controls p-to-e sensitivity.</p>
              <FieldError field="epsilon" errors={fieldErrors} />
            </div>
            <div>
              <label className={LABEL_CLASS}>Sensor freshness (s)</label>
              <input
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
              <label className={LABEL_CLASS}>Sensor identity</label>
              <select
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
