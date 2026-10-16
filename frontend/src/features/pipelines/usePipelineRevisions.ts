import { useEffect, useState } from "react";
import type { PipelineRevisionPage } from "@/types/pipelines.generated";
import { getErrorMessage } from "@/lib/errors";
import { pipelinesApi } from "./api";
import type { PipelineRevisionView, PipelineView } from "./contracts";

type RevisionResult = { id: string; attempt: number } & (
  | { revision: PipelineRevisionView; error?: never }
  | { error: string; revision?: never }
);

/** Revision summaries are paged; only the selected immutable graph is fetched. */
export function usePipelineRevisions(base: PipelineView, revisionId?: string) {
  const [snapshot, setSnapshot] = useState<RevisionResult>();
  const [older, setOlder] = useState<PipelineRevisionPage>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!revisionId) return;
    const controller = new AbortController();
    void pipelinesApi.revision(base.id, revisionId, controller.signal).then(
      (revision) => {
        if (!controller.signal.aborted)
          setSnapshot({ id: revisionId, attempt, revision });
      },
      (reason) => {
        if (!controller.signal.aborted)
          setSnapshot({ id: revisionId, attempt, error: getErrorMessage(reason) });
      },
    );
    return () => controller.abort();
  }, [base.id, revisionId, attempt]);
  const current =
    snapshot && snapshot.id === revisionId && snapshot.attempt === attempt
      ? snapshot
      : undefined;
  const revision = current?.revision;
  const summaries = new Map(
    [...base.revisions, ...(older?.items ?? [])].map((item) => [item.id, item]),
  );
  if (revision) summaries.set(revision.id, revision);
  const before = older ? older.next_before : base.revision_next_before;
  return {
    revision,
    error: current?.error ?? error,
    busy,
    before,
    summaries: [...summaries.values()].sort((a, b) => b.number - a.number),
    retry: () => setAttempt((value) => value + 1),
    loadOlder: async () => {
      if (!before || busy) return;
      setBusy(true);
      setError("");
      try {
        const page = await pipelinesApi.revisions(base.id, before);
        setOlder((current) => ({
          ...page,
          items: [...(current?.items ?? []), ...page.items],
        }));
      } catch (reason) {
        setError(getErrorMessage(reason));
      } finally {
        setBusy(false);
      }
    },
  };
}
