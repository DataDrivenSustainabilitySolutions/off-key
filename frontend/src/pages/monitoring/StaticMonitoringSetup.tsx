import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { API_CONFIG } from "@/lib/api-config";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { cn } from "@/lib/utils";
import type { ActiveService, ModelDefinition } from "@/types/monitoring";
import {
  Activity,
  Database,
  FlaskConical,
  Layers3,
  LockKeyhole,
  RadioTower,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { AdvancedSettings } from "./AdvancedSettings";
import {
  buildStaticMonitoringRequest,
  createDefaultStaticDraft,
  FIXED_VILLE_THRESHOLD,
  getModelDefaults,
  humanize,
  parseTopicPatterns,
} from "./config";
import type {
  FieldErrors,
  TopicMode,
} from "./config";
import {
  CONTROL_CLASS,
  errorId,
  HELP_CLASS,
  LABEL_CLASS,
} from "./formStyles";
import {
  ConfigSection,
  FieldError,
  LaneCard,
  LifecycleStep,
} from "./MonitoringUi";

interface StaticMonitoringSetupProps {
  chargerId: string;
  sensorTypes: string[];
  claimsBySensor: Map<string, ActiveService>;
  staticModels: Record<string, ModelDefinition>;
  loadingModels: boolean;
  onStarted: () => Promise<void>;
}

export function StaticMonitoringSetup({
  chargerId,
  sensorTypes,
  claimsBySensor,
  staticModels,
  loadingModels,
  onStarted,
}: StaticMonitoringSetupProps) {
  const [draft, setDraft] = useState(createDefaultStaticDraft);
  const [topicMode, setTopicMode] =
    useState<TopicMode>("selected_sensors");
  const [topicPatternInput, setTopicPatternInput] = useState("");
  const [selectedSensors, setSelectedSensors] = useState<
    Record<string, boolean>
  >({});
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [starting, setStarting] = useState(false);

  const availableSelectedSensors = useMemo(
    () =>
      sensorTypes.filter(
        (sensor) =>
          !claimsBySensor.has(sensor) && (selectedSensors[sensor] ?? true),
      ),
    [claimsBySensor, selectedSensors, sensorTypes],
  );
  const effectiveTopics = useMemo(
    () =>
      topicMode === "selected_sensors"
        ? availableSelectedSensors.map(
            (sensor) => `charger/${chargerId}/live-telemetry/${sensor}`,
          )
        : parseTopicPatterns(topicPatternInput),
    [availableSelectedSensors, chargerId, topicMode, topicPatternInput],
  );
  const modelDefinition = staticModels[draft.modelType];
  const modelProperties = modelDefinition?.parameters?.properties ?? {};

  const clearError = useCallback((field: string) => {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);

  const selectModel = (modelType: string) => {
    setDraft((current) => ({
      ...current,
      modelType,
      modelParams: getModelDefaults(modelType, staticModels[modelType]),
    }));
    setFieldErrors({});
  };

  const submit = async () => {
    if (!chargerId || !draft.modelType) return;
    const validation = buildStaticMonitoringRequest({
      chargerId,
      topics: effectiveTopics,
      draft,
      modelDefinition,
      containerName: `radar-${chargerId}-${Date.now()}`,
    });
    if (!validation.request) {
      setFieldErrors(validation.errors);
      toast.error("Fix the highlighted fields before starting monitoring.");
      return;
    }

    setStarting(true);
    try {
      await apiUtils.post(
        API_CONFIG.ENDPOINTS.MONITORING.START,
        validation.request,
        { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT },
      );
      toast.success("Static monitoring service started.");
      await onStarted();
    } catch (error) {
      toast.error(`Failed to start monitoring: ${getErrorMessage(error)}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <>
      <SectionPanel
        title="Choose a monitoring lane"
        description="Each lane has a distinct dependency assumption."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <LaneCard
            title="Static relationships"
            eyebrow="Selected"
            description="For signals such as L1, L2, and L3 whose dependency structure should remain stable. Train once, calibrate next, then produce online evidence."
            selected
            icon={Database}
          />
          <LaneCard
            title="Temporally dependent streams"
            eyebrow="Dynamic lane"
            description="Reserved for evolving temporal dependence. This is intentionally a facade only: no model, preprocessing, or runtime logic is attached yet."
            icon={Activity}
          />
        </div>
      </SectionPanel>

      <SectionPanel
        title="Static evidence lifecycle"
        description="Chronological samples; one purpose per phase."
      >
        <div className="grid gap-4 lg:grid-cols-3">
          <LifecycleStep
            number={1}
            title="Learn the baseline"
            description="Fit the detector on the first block of aligned sensor vectors."
            icon={Layers3}
          />
          <LifecycleStep
            number={2}
            title="Calibrate scores"
            description="Use a separate subsequent block to obtain conformal p-values."
            icon={FlaskConical}
          />
          <LifecycleStep
            number={3}
            title="Accumulate evidence"
            description="Transform p-values into e-values and update the native restarted mixture."
            icon={Sparkles}
          />
        </div>
      </SectionPanel>

      <SectionPanel
        title="Configure static monitoring"
        description="Select unassigned sensors, the detector, and the two sample blocks."
        actions={
          <Button
            onClick={() => void submit()}
            disabled={starting || loadingModels}
          >
            <Send className="h-4 w-4" />
            {starting ? "Starting..." : "Start monitoring"}
          </Button>
        }
      >
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]">
          <div className="space-y-5">
            <ConfigSection
              title="Telemetry scope"
              description="Choose the concrete streams owned exclusively by this monitor."
              icon={RadioTower}
            >
              <label className={LABEL_CLASS}>Topic input mode</label>
              <select
                className={cn(CONTROL_CLASS, "mt-2")}
                value={topicMode}
                onChange={(event) =>
                  setTopicMode(
                    event.target.value === "direct_patterns"
                      ? "direct_patterns"
                      : "selected_sensors",
                  )
                }
              >
                <option value="selected_sensors">Select discovered sensors</option>
                <option value="direct_patterns">Enter MQTT topic patterns</option>
              </select>

              {topicMode === "selected_sensors" ? (
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {sensorTypes.map((sensor) => {
                    const owner = claimsBySensor.get(sensor);
                    const checked =
                      !owner && (selectedSensors[sensor] ?? true);
                    return (
                      <label
                        key={sensor}
                        className={cn(
                          "flex items-start gap-3 rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow]",
                          owner
                            ? "cursor-not-allowed border-border/60 bg-muted/35 opacity-65"
                            : checked
                              ? "cursor-pointer border-primary/25 bg-primary/[0.035] shadow-xs"
                              : "cursor-pointer border-border/70 bg-card hover:border-primary/20",
                        )}
                      >
                        <input
                          type="checkbox"
                          className="mt-1 size-4 accent-primary"
                          checked={checked}
                          disabled={Boolean(owner)}
                          onChange={(event) =>
                            setSelectedSensors((current) => ({
                              ...current,
                              [sensor]: event.target.checked,
                            }))
                          }
                        />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">
                            {humanize(sensor)}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {owner
                              ? `Assigned to ${owner.container_name}`
                              : sensor}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                  {!sensorTypes.length && (
                    <p className="col-span-full rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                      No telemetry types discovered yet.
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-4">
                  <textarea
                    className={cn(CONTROL_CLASS, "min-h-28 resize-y")}
                    value={topicPatternInput}
                    onChange={(event) =>
                      setTopicPatternInput(event.target.value)
                    }
                    placeholder={`One concrete sensor per line, e.g. charger/${chargerId}/live-telemetry/L1`}
                  />
                  <p className={HELP_CLASS}>
                    Namespaces stay distinct. The backend verifies wildcard overlap
                    before creation.
                  </p>
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
              <select
                className={cn(CONTROL_CLASS, "mt-2")}
                value={draft.modelType}
                disabled={loadingModels}
                onChange={(event) => selectModel(event.target.value)}
              >
                {!staticModels[draft.modelType] && (
                  <option value={draft.modelType}>
                    {humanize(draft.modelType)}
                  </option>
                )}
                {Object.entries(staticModels).map(([key, model]) => (
                  <option key={key} value={key}>
                    {model.name || humanize(key)}
                  </option>
                ))}
              </select>
              <p className={HELP_CLASS}>
                {modelDefinition?.description ||
                  "A train-once PyOD detector for stable multivariate structure."}
              </p>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                {(
                  [
                    [
                      "trainingWindow",
                      "Training samples",
                      20,
                      "Phase 1: fit the fixed baseline.",
                    ],
                    [
                      "calibrationWindow",
                      "Calibration samples",
                      1,
                      "Phase 2: calibrate on later data.",
                    ],
                  ] as const
                ).map(([field, label, min, help]) => (
                  <div key={field}>
                    <label className={LABEL_CLASS}>{label}</label>
                    <input
                      type="number"
                      min={min}
                      className={cn(CONTROL_CLASS, "mt-2")}
                      value={draft[field]}
                      aria-invalid={Boolean(fieldErrors[field])}
                      aria-describedby={
                        fieldErrors[field] ? errorId(field) : undefined
                      }
                      onChange={(event) => {
                        setDraft((current) => ({
                          ...current,
                          [field]: event.target.value,
                        }));
                        clearError(field);
                      }}
                    />
                    <p className={HELP_CLASS}>{help}</p>
                    <FieldError field={field} errors={fieldErrors} />
                  </div>
                ))}
              </div>
            </ConfigSection>

            <AdvancedSettings
              draft={draft}
              modelProperties={modelProperties}
              fieldErrors={fieldErrors}
              setDraft={setDraft}
              clearError={clearError}
            />
          </div>

          <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
            <div className="overflow-hidden rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.055] p-5">
              <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
                <ShieldCheck className="h-5 w-5" />
                <h3 className="font-semibold">Fixed Ville threshold</h3>
              </div>
              <div className="mt-5 flex items-end justify-between gap-3">
                <div className="text-5xl font-semibold tracking-[-0.05em] tabular-nums">
                  {FIXED_VILLE_THRESHOLD}
                </div>
                <span className="mb-1 rounded-full border border-emerald-500/25 bg-background/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-700 dark:text-emerald-300">
                  Fixed
                </span>
              </div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                The native restarted mixture fires on a new crossing of 100. It
                is not manually reset and the threshold is not configurable.
              </p>
            </div>
            <div className="rounded-2xl border border-border/65 bg-card p-5">
              <div className="flex items-center gap-2">
                <LockKeyhole className="h-4 w-4 text-primary" />
                <h3 className="font-semibold">Assignment summary</h3>
              </div>
              <dl className="mt-4 divide-y divide-border/60 text-sm">
                <div className="flex justify-between gap-4 py-3 first:pt-0">
                  <dt className="text-muted-foreground">Selected streams</dt>
                  <dd className="font-medium tabular-nums">
                    {effectiveTopics.length}
                  </dd>
                </div>
                <div className="flex justify-between gap-4 py-3">
                  <dt className="text-muted-foreground">Already assigned</dt>
                  <dd className="font-medium tabular-nums">
                    {claimsBySensor.size}
                  </dd>
                </div>
                <div className="flex justify-between gap-4 py-3 last:pb-0">
                  <dt className="text-muted-foreground">Alignment</dt>
                  <dd className="font-medium">Strict barrier</dd>
                </div>
              </dl>
            </div>
            <div className="rounded-2xl border border-amber-500/25 bg-amber-500/[0.045] p-5 text-sm leading-6 text-muted-foreground">
              Evidence assumes the static calibration remains representative.
              Temporal dependence is intentionally deferred to the future dynamic
              lane.
            </div>
          </aside>
        </div>
      </SectionPanel>
    </>
  );
}
