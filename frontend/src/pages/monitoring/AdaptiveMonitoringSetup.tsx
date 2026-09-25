import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { buildDeviceTelemetryTopic } from "@/lib/mqtt-topics";
import { cn } from "@/lib/utils";
import type { ActiveService, ModelDefinition } from "@/types/monitoring";
import { BrainCircuit, FlaskConical, Gauge, Layers3, RadioTower, Send, SlidersHorizontal } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  buildAdaptiveMonitoringRequest,
  createDefaultAdaptiveDraft,
  getModelDefaults,
  humanize,
} from "./config";
import type { FieldErrors } from "./config";
import { CONTROL_CLASS, HELP_CLASS, LABEL_CLASS } from "./formStyles";
import { ConfigSection, FieldError, LifecycleStep } from "./MonitoringUi";
import { ModelParameterFields } from "./ModelParameterFields";

interface Props {
  chargerId: string;
  sensorTypes: string[];
  claimsBySensor: Map<string, ActiveService>;
  adaptiveModels: Record<string, ModelDefinition>;
  loadingModels: boolean;
  onStarted: () => Promise<void>;
}

export function AdaptiveMonitoringSetup({
  chargerId,
  sensorTypes,
  claimsBySensor,
  adaptiveModels,
  loadingModels,
  onStarted,
}: Props) {
  const [draft, setDraft] = useState(createDefaultAdaptiveDraft);
  const [selectedSensors, setSelectedSensors] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [starting, setStarting] = useState(false);
  const availableSensors = useMemo(
    () => sensorTypes.filter((sensor) => !claimsBySensor.has(sensor)),
    [claimsBySensor, sensorTypes],
  );
  const activeSensors = useMemo(
    () => availableSensors.filter((sensor) => selectedSensors[sensor] ?? true),
    [availableSensors, selectedSensors],
  );
  const effectiveFeatureCount = draft.projection === "none"
    ? activeSensors.length
    : Number(draft.projectionComponents) || 0;
  const compatibleModels = useMemo(
    () => Object.fromEntries(Object.entries(adaptiveModels).filter(([, definition]) => {
      const limits = definition.default_capabilities?.feature_count;
      return definition.available !== false
        && effectiveFeatureCount >= (limits?.minimum ?? 1)
        && (limits?.maximum == null || effectiveFeatureCount <= limits.maximum);
    })),
    [adaptiveModels, effectiveFeatureCount],
  );
  const modelDefinition = adaptiveModels[draft.modelType];
  const groupedModels = useMemo(() => {
    const groups: Record<string, Array<[string, ModelDefinition]>> = {};
    for (const entry of Object.entries(adaptiveModels)) {
      const group = humanize(entry[1].algorithm_family ?? "Other models");
      (groups[group] ??= []).push(entry);
    }
    return groups;
  }, [adaptiveModels]);

  const clearError = useCallback((field: string) => {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);

  const submit = async () => {
    const topics = activeSensors.map((sensor) =>
      buildDeviceTelemetryTopic(chargerId, sensor),
    );
    const validation = buildAdaptiveMonitoringRequest({
      chargerId,
      topics,
      draft,
      modelDefinition,
      containerName: `radar-adaptive-${chargerId}-${Date.now()}`,
    });
    if (!validation.request) {
      setFieldErrors(validation.errors);
      toast.error("Fix the highlighted fields before starting monitoring.");
      return;
    }
    setStarting(true);
    try {
      await apiUtils.post(API_CONFIG.ENDPOINTS.MONITORING.START, validation.request, {
        timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT,
      });
      toast.success("Adaptive monitoring service started.");
      await onStarted();
    } catch (error) {
      toast.error(`Failed to start adaptive monitoring: ${getErrorMessage(error)}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <>
      <SectionPanel title="Adaptive stream lifecycle" description="The model adapts to every valid point, while the calibrated threshold stays fixed for this service run.">
        <div className="grid gap-4 lg:grid-cols-3">
          <LifecycleStep number={1} title="Warm up" description="Learn each aligned vector without scoring it." icon={Layers3} />
          <LifecycleStep number={2} title="Calibrate" description="Score first, learn second, and retain the score distribution for threshold calibration." icon={FlaskConical} />
          <LifecycleStep number={3} title="Monitor and adapt" description="Compare each pre-learning score with the frozen threshold, then learn every point including anomalies." icon={BrainCircuit} />
        </div>
      </SectionPanel>

      <SectionPanel
        title="Configure adaptive monitoring"
        description="Choose exclusive telemetry streams, a compatible Aberrant detector, preprocessing, and lifecycle windows."
        actions={<Button onClick={() => void submit()} disabled={starting || loadingModels || !draft.modelType}><Send className="size-4" />{starting ? "Starting..." : "Start adaptive monitoring"}</Button>}
      >
        <div className="space-y-5">
          <ConfigSection title="Telemetry scope" description="Each concrete sensor can be owned by only one active monitor." icon={RadioTower}>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {sensorTypes.map((sensor) => {
                const owner = claimsBySensor.get(sensor);
                const checked = !owner && (selectedSensors[sensor] ?? true);
                return (
                  <label key={sensor} className={cn("flex items-center gap-3 rounded-xl border p-3 text-sm", owner && "opacity-50")}>
                    <input type="checkbox" checked={checked} disabled={Boolean(owner)} onChange={(event) => {
                      setSelectedSensors((current) => ({ ...current, [sensor]: event.target.checked }));
                      clearError("topics");
                    }} />
                    <span className="min-w-0"><span className="block truncate font-medium">{sensor}</span>{owner && <span className="block truncate text-xs text-muted-foreground">Owned by {owner.container_name}</span>}</span>
                  </label>
                );
              })}
            </div>
            {!sensorTypes.length && <p className={HELP_CLASS}>No telemetry sensors have been discovered.</p>}
            <FieldError field="topics" errors={fieldErrors} />
          </ConfigSection>

          <div className="grid gap-5 xl:grid-cols-2">
            <ConfigSection title="Detector" description={`${Object.keys(compatibleModels).length} of ${Object.keys(adaptiveModels).length} models support the current ${effectiveFeatureCount}-feature schema.`} icon={BrainCircuit}>
              <label className={LABEL_CLASS} htmlFor="adaptive-model">Aberrant model</label>
              <select id="adaptive-model" className={cn(CONTROL_CLASS, "mt-2")} value={draft.modelType} onChange={(event) => {
                const modelType = event.target.value;
                const requiresUnitInterval = adaptiveModels[modelType]?.default_capabilities?.requires_unit_interval;
                setDraft((current) => ({
                  ...current, modelType,
                  modelParams: getModelDefaults(modelType, adaptiveModels[modelType]),
                  ...(requiresUnitInterval ? { scaler: "min_max_scaler" as const, minMaxLower: "0", minMaxUpper: "1", projection: "none" as const } : {}),
                }));
                setFieldErrors({});
              }}>
                {Object.entries(groupedModels).map(([group, entries]) => entries.length ? <optgroup key={group} label={group}>{entries.map(([id, definition]) => <option key={id} value={id} disabled={!compatibleModels[id]}>{definition.name ?? humanize(id)}{definition.available === false ? " (unavailable)" : compatibleModels[id] ? "" : " (incompatible feature count)"}</option>)}</optgroup> : null)}
              </select>
              <FieldError field="modelType" errors={fieldErrors} />
              {modelDefinition?.default_capabilities?.requires_unit_interval && <p className={HELP_CLASS}>This detector requires values between 0 and 1. Min-max scaling clips new extremes to that range; projections are unsupported.</p>}
              {modelDefinition?.default_capabilities?.state === "growing" && <p className={HELP_CLASS}>This detector's memory can grow during monitoring. Watch service memory usage on long runs.</p>}
              {modelDefinition?.algorithm_family === "time_series" && <p className={HELP_CLASS}>Windows count aligned observations, not seconds. Use consistently sampled telemetry to compare time-series shapes.</p>}
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <ModelParameterFields
                  properties={modelDefinition?.parameters?.properties ?? {}}
                  values={{ ...getModelDefaults(draft.modelType, modelDefinition), ...draft.modelParams }}
                  errors={fieldErrors}
                  onChange={(modelParams, field) => {
                    setDraft((current) => ({ ...current, modelParams }));
                    clearError(field);
                  }}
                />
              </div>
            </ConfigSection>

            <ConfigSection title="Lifecycle and threshold" description="Calibration uses the higher empirical quantile; 1.0 is exactly the largest observed calibration score." icon={Gauge}>
              <div className="grid gap-4 sm:grid-cols-3">
                {([['trainingWindow', 'Warm-up samples', 1], ['calibrationWindow', 'Calibration samples', 1], ['thresholdQuantile', 'Threshold quantile', 0.000001]] as const).map(([field, label, min]) => <div key={field}><label className={LABEL_CLASS} htmlFor={`adaptive-${field}`}>{label}</label><input id={`adaptive-${field}`} type="number" min={min} max={field === 'thresholdQuantile' ? 1 : undefined} step={field === 'thresholdQuantile' ? '0.001' : 1} className={cn(CONTROL_CLASS, "mt-2")} value={draft[field]} onChange={(event) => { setDraft((current) => ({ ...current, [field]: event.target.value })); clearError(field); }} /><FieldError field={field} errors={fieldErrors} /></div>)}
              </div>
            </ConfigSection>
          </div>

          <ConfigSection title="Preprocessing" description="Optionally apply one scaler, followed by one projection. The projected feature count controls model compatibility." icon={SlidersHorizontal}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div><label className={LABEL_CLASS} htmlFor="adaptive-scaler">Scaler</label><select id="adaptive-scaler" className={cn(CONTROL_CLASS, "mt-2")} value={draft.scaler} onChange={(event) => setDraft((current) => ({ ...current, scaler: event.target.value as typeof current.scaler }))}><option value="none">None</option><option value="standard_scaler">Standard scaler</option><option value="min_max_scaler">Min-max scaler</option></select></div>
              {draft.scaler === "standard_scaler" && <div><span className={LABEL_CLASS}>Standard deviation</span><label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.scalerWithStd} onChange={(event) => setDraft((current) => ({ ...current, scalerWithStd: event.target.checked }))} />Scale to unit variance</label></div>}
              {draft.scaler === "min_max_scaler" && <><div><label className={LABEL_CLASS} htmlFor="adaptive-min-max-lower">Range minimum</label><input id="adaptive-min-max-lower" type="number" step="any" className={cn(CONTROL_CLASS, "mt-2")} value={draft.minMaxLower} onChange={(event) => setDraft((current) => ({ ...current, minMaxLower: event.target.value }))} /><FieldError field="minMaxLower" errors={fieldErrors} /></div><div><label className={LABEL_CLASS} htmlFor="adaptive-min-max-upper">Range maximum</label><input id="adaptive-min-max-upper" type="number" step="any" className={cn(CONTROL_CLASS, "mt-2")} value={draft.minMaxUpper} onChange={(event) => setDraft((current) => ({ ...current, minMaxUpper: event.target.value }))} /><FieldError field="minMaxUpper" errors={fieldErrors} /></div></>}
              <div><label className={LABEL_CLASS} htmlFor="adaptive-projection">Projection</label><select id="adaptive-projection" className={cn(CONTROL_CLASS, "mt-2")} value={draft.projection} onChange={(event) => setDraft((current) => ({ ...current, projection: event.target.value as typeof current.projection }))}><option value="none">None</option><option value="incremental_pca">Incremental PCA</option><option value="random_projection">Random projection</option></select></div>
              {draft.projection !== "none" && <div><label className={LABEL_CLASS} htmlFor="adaptive-components">Components</label><input id="adaptive-components" type="number" min={1} step={1} className={cn(CONTROL_CLASS, "mt-2")} value={draft.projectionComponents} onChange={(event) => setDraft((current) => ({ ...current, projectionComponents: event.target.value }))} /><FieldError field="projectionComponents" errors={fieldErrors} /></div>}
              {draft.projection === "incremental_pca" && <div><label className={LABEL_CLASS} htmlFor="adaptive-projection-n0">PCA initialization</label><input id="adaptive-projection-n0" type="number" min={2} step={1} className={cn(CONTROL_CLASS, "mt-2")} value={draft.projectionN0} onChange={(event) => setDraft((current) => ({ ...current, projectionN0: event.target.value }))} /><FieldError field="projectionN0" errors={fieldErrors} /></div>}
              {draft.projection === "incremental_pca" && <><div><label className={LABEL_CLASS} htmlFor="adaptive-projection-tolerance">PCA tolerance</label><input id="adaptive-projection-tolerance" type="number" min={0} step="any" className={cn(CONTROL_CLASS, "mt-2")} value={draft.projectionTolerance} onChange={(event) => setDraft((current) => ({ ...current, projectionTolerance: event.target.value }))} /><FieldError field="projectionTolerance" errors={fieldErrors} /></div><div><label className={LABEL_CLASS} htmlFor="adaptive-projection-forgetting">Forgetting factor</label><input id="adaptive-projection-forgetting" type="number" min={0} max={0.999999} step="any" placeholder="None" className={cn(CONTROL_CLASS, "mt-2")} value={draft.projectionForgettingFactor} onChange={(event) => setDraft((current) => ({ ...current, projectionForgettingFactor: event.target.value }))} /><FieldError field="projectionForgettingFactor" errors={fieldErrors} /></div></>}
              {draft.projection === "random_projection" && <div><label className={LABEL_CLASS} htmlFor="adaptive-projection-seed">Projection seed</label><input id="adaptive-projection-seed" type="number" step={1} className={cn(CONTROL_CLASS, "mt-2")} value={draft.projectionSeed} onChange={(event) => setDraft((current) => ({ ...current, projectionSeed: event.target.value }))} /><FieldError field="projectionSeed" errors={fieldErrors} /></div>}
            </div>
          </ConfigSection>
        </div>
      </SectionPanel>
    </>
  );
}
