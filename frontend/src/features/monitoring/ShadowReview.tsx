import { useEffect, useState } from "react";
import { Play, Square } from "lucide-react";
import toast from "react-hot-toast";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import { RelativeTime } from "@/components/RelativeTime";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";
import { useNow } from "@/hooks/use-now";
import { DAY, mutedAlarms, shadowSince } from "@/domain/monitoring/shadowReview";
import { LOCALE } from "@/lib/locale";

/**
 * A shadow run under review: how long it has run, the alarms it held back, how often against what
 * its test said, and the two ways out. Taking it live goes through the Pipeline tab.
 */
export function ShadowReview({ service, canEdit, onTakeLive, onStopped }: {
  service: ActiveService;
  canEdit: boolean;
  onTakeLive: () => void;
  onStopped?: () => void | Promise<void>;
}) {
  const since = shadowSince(service);
  const [alarms, setAlarms] = useState<{ observations: number; episodes: number }>();
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState("");

  useEffect(() => {
    if (!service.reading_ids.length) return;
    const controller = new AbortController();
    void apiUtils.get<MonitoringChartEvidence[]>(API_CONFIG.ENDPOINTS.MONITORING.ALARMS(service.id, service.reading_ids),
      { signal: controller.signal }).then(rows => {
      if (!controller.signal.aborted) { setAlarms(mutedAlarms(rows, since)); setError(""); }
    }, reason => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); });
    return () => controller.abort();
  }, [service.id, service.reading_ids, since]);

  const now = useNow(60_000, !!since);
  const days = since ? Math.max(0, (now - Date.parse(since)) / DAY) : 0;
  const perDay = alarms && days >= 1 ? alarms.episodes / days : undefined;
  const expected = service.origin?.rationale?.evidence;

  const stop = async () => {
    setStopping(true); setStopError("");
    try {
      await apiUtils.post(API_CONFIG.ENDPOINTS.MONITORING.STOP(service.id), { note: "Stopped after review of its shadow run." },
        { timeout: API_CONFIG.MONITORING_LIFECYCLE_TIMEOUT });
      setConfirm(false); toast.success("Shadow run stopped.");
      await onStopped?.();
    } catch (reason) { setStopError(getErrorMessage(reason)); }
    finally { setStopping(false); }
  };

  return <section className="mn-section mn-shadow-review" aria-label="Shadow run review">
    <h3>Shadow run</h3>
    <p className="ex-muted">It records the alarms it would raise and raises none.</p>
    <dl className="mn-configuration">
      <div><dt>Running since</dt><dd><RelativeTime value={since} fallback="Not recorded" /></dd></div>
      <div><dt>Muted alarms</dt><dd>{error ? <span role="alert">{error}</span> : !alarms ? "Counting…"
        : `${alarms.episodes.toLocaleString(LOCALE)} ${alarms.episodes === 1 ? "alarm" : "alarms"}`
          + (alarms.observations !== alarms.episodes ? ` over ${alarms.observations.toLocaleString(LOCALE)} observations` : "")}</dd></div>
      <div><dt>Per day</dt><dd>{perDay !== undefined ? perDay.toLocaleString(LOCALE, { maximumFractionDigits: 1 })
        : alarms ? "After its first day" : "…"}</dd></div>
      {expected && <div><dt>The test said</dt><dd>{expected}</dd></div>}
    </dl>
    {canEdit && <div className="mn-shadow-actions">
      <button type="button" className="mn-primary" onClick={onTakeLive}><Play size={14} aria-hidden="true" />Take live</button>
      <button type="button" onClick={() => { setStopError(""); setConfirm(true); }}><Square size={13} aria-hidden="true" />Stop</button>
    </div>}
    {canEdit && <p className="ex-muted mn-shadow-hint">Take live opens the Pipeline tab: choose Edit monitor and update it without Shadow run.</p>}
    <ConfirmDialog open={confirm} title="Stop the shadow run?" description="It stops recording. Its history and the alarms it held back stay."
      confirmLabel="Stop" busyLabel="Stopping…" busy={stopping} error={stopError}
      onConfirm={() => void stop()} onCancel={() => setConfirm(false)} />
  </section>;
}
