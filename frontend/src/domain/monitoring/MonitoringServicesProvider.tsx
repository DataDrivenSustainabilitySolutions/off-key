import { useCallback, useMemo, useState, type ReactNode } from "react";
import { FeedContext, useWorkspacePoll, type Registration } from "./useMonitoringServices";

/**
 * Every view under the workspace shares one service-list poll, at the
 * shortest interval any mounted consumer asks for; with no consumer it stops.
 */
export function MonitoringServicesProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const [registrations, setRegistrations] = useState<ReadonlyMap<string, Registration>>(new Map());
  const wanted = [...registrations.values()];
  const intervalMs = Math.min(...wanted.map(item => item.intervalMs));
  const selectedServiceId = wanted.find(item => item.selectedServiceId)?.selectedServiceId;
  const poll = useWorkspacePoll(enabled && wanted.length > 0, Number.isFinite(intervalMs) ? intervalMs : 20_000, selectedServiceId);
  const register = useCallback((id: string, registration: Registration) => {
    setRegistrations(previous => new Map(previous).set(id, registration));
    return () => setRegistrations(previous => {
      const next = new Map(previous);
      next.delete(id);
      return next;
    });
  }, []);
  const value = useMemo(() => ({ ...poll, register }), [poll, register]);
  return <FeedContext.Provider value={value}>{children}</FeedContext.Provider>;
}
