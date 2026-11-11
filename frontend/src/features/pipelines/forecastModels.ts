import { useCallback, useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/errors";
import type { ForecastModelCatalog, ForecastModelInfo } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";
import type { PipelineComponent } from "./contracts";

/** A step whose model lives in the deployment's forecast service, not in the monitor. */
export const usesForecastService = (component: string) => component.startsWith("forecast.");

export const NO_FORECAST_SERVICE = "This deployment has no forecast service, which this step needs.";

/** Mark the steps this deployment cannot run, so no menu offers them. A service that
 * only does not answer right now leaves them on offer. */
export function withForecastService(components: PipelineComponent[], catalog?: ForecastModelCatalog) {
  if (catalog?.service !== "not_deployed") return components;
  return components.map((component) => usesForecastService(component.id)
    ? { ...component, unavailable: NO_FORECAST_SERVICE } : component);
}

export type CheckpointRow = {
  id: string;
  label: string;
  /** Undefined when the service does not offer the checkpoint. */
  model?: ForecastModelInfo;
};

/** One row per checkpoint the step can use, in the order its setting lists them. */
export function checkpointRows(component: PipelineComponent, catalog: ForecastModelCatalog): CheckpointRow[] {
  const options = component.fields.find((field) => field.name === "checkpoint")?.options ?? [];
  return options.map(String).map((id) => {
    const model = catalog.models?.find((item) => item.id === id);
    return { id, label: model?.label ?? id.split("/").pop() ?? id, model };
  });
}

export function sizeText(bytes: number) {
  if (!bytes) return "";
  const gigabytes = bytes >= 1_000_000_000;
  const value = bytes / (gigabytes ? 1_000_000_000 : 1_000_000);
  return `${value.toLocaleString("en", { maximumFractionDigits: gigabytes ? 1 : 0 })} ${gigabytes ? "GB" : "MB"}`;
}

/** A checkpoint's state in words; a download says how far it is. */
export function stateText(model?: ForecastModelInfo) {
  if (!model) return "Not offered here";
  if (model.status === "ready") return "Ready";
  if (model.status === "failed") return "Download failed";
  if (model.status === "downloading")
    return model.progress == null ? "Downloading" : `Downloading, ${Math.round(model.progress * 100)}%`;
  return "Not downloaded";
}

/** A download in progress is asked about this often. */
const POLL_MS = 3000;

export type ForecastModels = {
  /** Undefined until the first answer, and when the state could not be read. */
  catalog?: ForecastModelCatalog;
  /** Why the state could not be read, or why a download did not start. */
  error?: string;
  download: (model: string) => void;
  refresh: () => void;
};

/** What the forecast service holds, asked through the API and followed while a
 * checkpoint downloads. */
export function useForecastModels(enabled: boolean): ForecastModels {
  const [catalog, setCatalog] = useState<ForecastModelCatalog>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const next = await pipelinesApi.forecastModels(controller.signal);
        if (controller.signal.aborted) return;
        setCatalog(next);
        if (next.models?.some((model) => model.status === "downloading")) timer = window.setTimeout(load, POLL_MS);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setCatalog(undefined);
        setError(getErrorMessage(reason));
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [enabled, attempt]);
  const refresh = useCallback(() => {
    setError(undefined);
    setAttempt((value) => value + 1);
  }, []);
  const download = useCallback((model: string) => {
    setError(undefined);
    void pipelinesApi.downloadForecastModel(model).then(
      (started) => {
        // The row changes at once; the list is then followed until the download ends.
        setCatalog((current) => current && {
          ...current,
          models: current.models?.map((item) => (item.id === started.id ? started : item)),
        });
        setAttempt((value) => value + 1);
      },
      (reason) => {
        setError(getErrorMessage(reason));
        setAttempt((value) => value + 1);
      },
    );
  }, []);
  return { catalog, error, download, refresh };
}
