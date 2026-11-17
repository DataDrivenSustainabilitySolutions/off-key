import { useEffect, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { RationaleCard } from "@/features/workspace/RationaleCard";
import type { MonitorOrigin } from "@/types/pipelines.generated";

/**
 * What the monitor that raised an alarm watches, beside its source. Without a recorded origin, or
 * once the monitor is gone, nothing shows: the alarm reads as before.
 */
export function MonitorWatches({ monitorId }: { monitorId: string }) {
  const [origin, setOrigin] = useState<MonitorOrigin | null>();
  useEffect(() => {
    const controller = new AbortController();
    void apiUtils.get<{ origin?: MonitorOrigin | null }>(API_CONFIG.ENDPOINTS.MONITORING.ITEM(monitorId),
      { signal: controller.signal, redirectOnUnauthorized: false }).then(
      result => { if (!controller.signal.aborted) setOrigin(result.origin ?? null); },
      () => { if (!controller.signal.aborted) setOrigin(null); });
    return () => controller.abort();
  }, [monitorId]);
  if (!origin?.rationale) return null;
  return <div className="rp-watches">
    <RationaleCard author={origin.author} authorKind={origin.author_kind} rationale={origin.rationale} />
  </div>;
}
