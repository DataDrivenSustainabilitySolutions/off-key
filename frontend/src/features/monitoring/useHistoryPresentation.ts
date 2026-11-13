import { useEffect, useState } from "react";
import { pipelinesApi } from "@/features/pipelines/api";
import { historyPresentation, type HistoryPresentation } from "./historyPresentation";

export function useHistoryPresentation(serviceId: string) {
  const [result, setResult] = useState<{ serviceId: string; presentation?: HistoryPresentation; error?: string }>();
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi.service(serviceId, controller.signal).then(view => {
      if (!controller.signal.aborted) setResult({ serviceId, presentation: historyPresentation(view) });
    }, () => {
      if (!controller.signal.aborted) setResult({ serviceId, error: "Reading associations could not be loaded. Forecasts remain on their feature scale." });
    });
    return () => controller.abort();
  }, [serviceId, retry]);
  return { ...(result?.serviceId === serviceId ? result : {}), retry: () => setRetry(value => value + 1) };
}
