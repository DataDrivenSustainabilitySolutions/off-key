import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineListPage } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";

/** Shared, bounded browsing for template selection and library management. */
export function PipelineDesignBrowser({
  onSelect,
  selecting = false,
  disabled = false,
}: {
  onSelect: (id: string) => void;
  selecting?: boolean;
  disabled?: boolean;
}) {
  const [result, setResult] = useState<{
    query: string;
    archived: boolean;
    page: PipelineListPage;
  }>();
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const page = result?.query === query && result.archived === archived
    ? result.page : undefined;

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void pipelinesApi.list({ query, archived }, controller.signal).then(
        (next) => {
          if (!controller.signal.aborted) {
            setResult({ query, archived, page: next });
            setError("");
          }
        },
        (reason) => {
          if (!controller.signal.aborted) setError(getErrorMessage(reason));
        },
      );
    }, query ? 300 : 0);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [retry, query, archived]);

  const loadMore = async () => {
    if (!page || page.next_offset == null || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const next = await pipelinesApi.list({ query, archived, offset: page.next_offset });
      setResult((current) => current?.page === page
        ? { query, archived, page: { ...next, items: [...page.items, ...next.items] } }
        : current);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setLoadingMore(false);
    }
  };

  return <div className="pl-design-browser">
    <div className="pl-library-tools">
      <label className="pl-search">
        <Search size={16} />
        <input type="search" aria-label="Search saved designs" placeholder="Search saved designs…"
          value={query} onChange={(event) => setQuery(event.target.value)} disabled={disabled} />
      </label>
      {!selecting && <label className="pl-check">
        <input type="checkbox" checked={archived}
          onChange={(event) => setArchived(event.target.checked)} />
        Archived designs
      </label>}
    </div>
    {error && <p role="alert" className="pl-error">{error}
      <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry designs</button>
    </p>}
    {!page ? <p role="status">Loading saved designs…</p> : !page.items.length ? <p className="pl-empty">
      {query ? "No matching designs." : archived ? "No archived designs."
        : "No saved designs yet. Start with a monitoring strategy to create one."}
    </p> : <ul className="pl-library-list">
      {page.items.map((pipeline) => <li key={pipeline.id}>
        <button type="button" disabled={disabled} onClick={() => onSelect(pipeline.id)}
          aria-label={`${selecting ? "Use" : "Open"} ${pipeline.name}`}>
          <strong>{pipeline.name}</strong>
          <span>{pipeline.description || "Reusable monitoring design"}</span>
          <small>{pipeline.strategy === "adaptive_stream" ? "Adaptive stream" : "Static baseline"}
            {" · "}{pipeline.revision_count
              ? selecting ? "Latest published revision" : `${pipeline.revision_count} published ${pipeline.revision_count === 1 ? "revision" : "revisions"}`
              : "Saved draft"}
          </small>
        </button>
      </li>)}
    </ul>}
    {page?.next_offset != null && <button type="button" disabled={loadingMore || disabled}
      onClick={() => void loadMore()}>Load more designs</button>}
  </div>;
}
