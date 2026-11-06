import { useState } from "react";
import { Link } from "react-router-dom";
import type { PipelineHistoryPage } from "@/types/pipelines.generated";
import { getErrorMessage } from "@/lib/errors";
import { pipelinesApi } from "./api";

export function PipelineRunHistory({ initial }: { initial: PipelineHistoryPage }) {
  const [page, setPage] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loadOlder = async () => {
    if (!page.next_monitor_id || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await pipelinesApi.history(page.next_monitor_id);
      const seen = new Set(page.items.map((run) => run.id));
      const items = [
        ...page.items,
        ...next.items.filter((run) => !seen.has(run.id)),
      ];
      setPage({
        items,
        next_monitor_id: items.some((run) => run.monitor_id === next.next_monitor_id)
          ? null
          : next.next_monitor_id,
      });
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="pl-history">
      <summary>
        Linked monitoring history ({page.items.length}{page.next_monitor_id ? "+" : ""})
      </summary>
      <ul>
        {page.items.map((run) => (
          <li key={run.id}>
            <Link
              to={`/?service=${encodeURIComponent(run.monitor_id)}&tab=pipeline`}
            >
              {run.id}
            </Link>{" "}
            · {run.status} · {run.created_at}
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="pl-error">{error}</p>
      )}
      {page.next_monitor_id && (
        <button disabled={busy} onClick={() => void loadOlder()}>
          Load older monitoring history
        </button>
      )}
    </details>
  );
}
