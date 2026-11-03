import { useEffect, useState } from "react";
import type { PipelineRunTimeline as Timeline } from "@/types/pipelines.generated";
import { getErrorMessage } from "@/lib/errors";
import { formatDateTime, formatExactDateTime } from "@/lib/format-time";
import { pipelinesApi } from "./api";
import { timelineEntry } from "./timeline";

/** What this run went through: setup phases, stages, gaps, crashes and its end. */
export function PipelineRunTimeline({ serviceId, failed = false }: { serviceId: string; failed?: boolean }) {
  const [open, setOpen] = useState(failed);
  const [timeline, setTimeline] = useState<Timeline>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [request, setRequest] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void pipelinesApi.timeline(serviceId, controller.signal).then(
      (next) => {
        if (controller.signal.aborted) return;
        setTimeline(next);
        setError("");
        setBusy(false);
      },
      (reason) => {
        if (controller.signal.aborted) return;
        setError(getErrorMessage(reason));
        setBusy(false);
      },
    );
    return () => controller.abort();
  }, [open, serviceId, request]);
  const refresh = () => { setBusy(true); setRequest((value) => value + 1); };
  const entries = (timeline?.events ?? []).map(timelineEntry).reverse();
  return (
    <details className="pl-history pl-timeline" open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>Run timeline{timeline ? ` (${timeline.events.length}${timeline.truncated ? "+" : ""})` : ""}</summary>
      {open && (
        <>
          <div className="pl-timeline-head">
            <p className="pl-help">Newest first. Kept after the service stops.</p>
            <button type="button" disabled={busy} onClick={refresh}>Refresh</button>
          </div>
          {timeline?.error && (
            <p className="pl-timeline-ended" role="status">
              Ended {timeline.ended_at ? formatDateTime(timeline.ended_at) : ""} with: {timeline.error}
            </p>
          )}
          {error && <p role="alert" className="pl-error">{error}</p>}
          {!timeline && !error && <p role="status">Loading timeline…</p>}
          {timeline && entries.length === 0 && (
            <p className="pl-help">No events yet. Runs started before this release have none.</p>
          )}
          {entries.length > 0 && (
            <ol className="pl-timeline-list">
              {entries.map((entry) => (
                <li key={entry.key} className={`pl-timeline-entry pl-timeline-entry--${entry.tone}`}>
                  <time dateTime={entry.at} title={formatExactDateTime(entry.at)}>{formatDateTime(entry.at)}</time>
                  <div>
                    <strong>{entry.title}</strong>
                    {entry.lines.map((line, index) => <p key={index}>{line}</p>)}
                  </div>
                </li>
              ))}
            </ol>
          )}
          {timeline?.truncated && <p className="pl-help">Older events are not shown.</p>}
        </>
      )}
    </details>
  );
}
