import { useNavigationDraft } from "@/lib/navigation-draft";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { buildDeviceTelemetryTopic } from "@/lib/mqtt-topics";
import { cn } from "@/lib/utils";
import type { ActiveService, ModelDefinition } from "@/types/monitoring";
import {
  Database,
  LockKeyhole,
  RadioTower,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { HelpTooltip } from "@/components/HelpTooltip";
import { SettingLabel } from "./SettingLabel";
import { startFormMonitor } from "./startMonitor";
import { AdvancedSettings } from "./AdvancedSettings";
import {
  buildStaticMonitoringRequest,
  createDefaultStaticDraft,
  getModelDefaults,
  humanize,
} from "./config";
import type { FieldErrors } from "./config";
import {
  CONTROL_CLASS,
  errorId,
} from "./formStyles";
import {
  ConfigSection,
  FieldError,
} from "./FormParts";

interface StaticMonitoringSetupProps {
  draftKey?: string;
  chargerId: string;
  sensorTypes: string[];
  claimsBySensor: Map<string, ActiveService>;
  staticModels: Record<string, ModelDefinition>;
  loadingModels: boolean;
  onStarted: (serviceId?: string) => Promise<void>;
  displayName?: string;
  initialReading?: string;
  sensorLabels?: Map<string, string>;
  sensorTopics?: Map<string, string>;
}

export function StaticMonitoringSetup({
  draftKey,
  chargerId,
  sensorTypes,
  claimsBySensor,
  staticModels,
  loadingModels,
  onStarted,
  initialReading, sensorLabels, sensorTopics, displayName,
}: StaticMonitoringSetupProps) {
  const [draft, setDraft] = useNavigationDraft(draftKey && `${draftKey}:parameters`, createDefaultStaticDraft);
  const [selectedSensors, setSelectedSensors] = useNavigationDraft<Record<string, boolean>>(draftKey && `${draftKey}:readings`, {});
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [starting, setStarting] = useState(false);

  const availableSelectedSensors = useMemo(
    () =>
      sensorTypes.filter(
        (sensor) =>
          !claimsBySensor.has(sensor) && (selectedSensors[sensor] ?? (!initialReading || sensor === initialReading)),
      ),
    [claimsBySensor, selectedSensors, sensorTypes, initialReading],
  );
  const effectiveTopics = useMemo(
    () => availableSelectedSensors.map(
      (sensor) => sensorTopics?.get(sensor) ?? buildDeviceTelemetryTopic(chargerId, sensor),
    ),
    [availableSelectedSensors, chargerId, sensorTopics],
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
      const serviceId = await startFormMonitor({
        ...validation.request,
        ...(displayName ? { display_name: displayName } : {}),
      });
      toast.success("Static monitoring service started.");
      await onStarted(serviceId);
    } catch (error) {
      toast.error(`Failed to start monitoring: ${getErrorMessage(error)}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <>
      <SectionPanel
        title="Configure static monitoring"
        help="Train the detector on the first sample block, calibrate p-values on a separate later block, then accumulate evidence. New threshold crossings create anomaly events."
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
              title="Readings"
              help="A reading can belong to one active monitor."
              icon={RadioTower}
            >
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {sensorTypes.map((sensor) => {
                  const owner = claimsBySensor.get(sensor);
                  const checked =
                    !owner && (selectedSensors[sensor] ?? (!initialReading || sensor === initialReading));
                  return (
                    <label
                      key={sensor}
                      className={cn(
                        "flex min-w-0 items-start gap-3 rounded-md border p-3 transition-colors",
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
                          {sensorLabels?.get(sensor) ?? humanize(sensor)}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {owner
                            ? `Assigned to ${owner.container_name}`
                            : sensorLabels?.has(sensor) ? "" : sensor}
                        </span>
                      </span>
                    </label>
                  );
                })}
                {!sensorTypes.length && (
                  <p className="col-span-full rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                    No recorded readings.
                  </p>
                )}
              </div>
              <FieldError field="topics" errors={fieldErrors} />
            </ConfigSection>

            <ConfigSection
              title="Baseline and sample windows"
              help="Training and calibration use separate, consecutive sample blocks."
              icon={Database}
            >
              <SettingLabel label="Detector" htmlFor="static-detector" help={modelDefinition?.description} />
              <select
                id="static-detector"
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
                    <SettingLabel label={label} htmlFor={`static-${field}`} help={help} />
                    <input
                      id={`static-${field}`}
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
                <h3 className="font-semibold">Martingale ensemble</h3>
                <HelpTooltip label="Martingale ensemble">Each tracker has a betting method, alarm statistic, and threshold. A new crossing by any tracker creates an anomaly.</HelpTooltip>
              </div>
              <div className="mt-5 flex items-end justify-between gap-3">
                <div className="text-5xl font-semibold tracking-[-0.05em] tabular-nums">
                  {draft.martingaleTrackers.length}
                </div>
                <span className="mb-1 rounded-full border border-emerald-500/25 bg-background/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-700 dark:text-emerald-300">
                  {draft.martingaleTrackers.length === 1 ? "Tracker" : "Trackers"}
                </span>
              </div>
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
              Static monitoring assumes calibration data remains representative.
            </div>
          </aside>
        </div>
      </SectionPanel>
    </>
  );
}
