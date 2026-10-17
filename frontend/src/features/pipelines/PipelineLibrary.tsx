import { useEffect, useState } from "react";
import { ArrowLeft, CopyPlus, Search } from "lucide-react";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineCatalog } from "./contracts";
import type { PipelineListPage } from "@/types/pipelines.generated";
import type { MonitoringTarget } from "../monitoring/serviceModel";
import { MonitoringTargetPicker } from "../monitoring/MonitoringTargetPicker";
import { pipelinesApi } from "./api";

type Props = {
  catalog: PipelineCatalog;
  canEdit: boolean;
  creating?: boolean;
  targets: MonitoringTarget[];
  initialTarget?: string;
  initialReading?: string;
  onOpen: (id: string) => void;
  onBack: () => void;
};

export function PipelineLibrary({
  catalog,
  canEdit,
  creating,
  targets,
  initialTarget,
  initialReading,
  onOpen,
  onBack,
}: Props) {
  const [result, setResult] = useState<{
    query: string;
    archived: boolean;
    page: PipelineListPage;
  }>();
  const [loadingMore, setLoadingMore] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [templateId, setTemplateId] = useState(
    catalog.templates.find(
      (template) => template.definition.strategy === "adaptive_stream",
    )?.id ??
      catalog.templates[0]?.id ??
      "",
  );
  const [name, setName] = useState("");
  const [targetId, setTargetId] = useState(initialTarget);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(!!creating);
  const [archived, setArchived] = useState(false);
  const page =
    result?.query === query && result.archived === archived
      ? result.page
      : undefined;
  const target = targets.find((item) => item.id === targetId);
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
      const next = await pipelinesApi.list({
        query, archived, offset: page.next_offset,
      });
      setResult((current) =>
        current?.page === page
          ? { query, archived, page: { ...next, items: [...page.items, ...next.items] } }
          : current,
      );
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setLoadingMore(false);
    }
  };
  const create = async () => {
    const template = catalog.templates.find((item) => item.id === templateId);
    if (!template || !name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const selected =
        target?.inputs.filter(
          (input) =>
            input.binding.policy.mode !== "off" &&
            (!initialReading || input.stream.id === initialReading),
        ) ?? [];
      const slots = selected.length
        ? selected.map((input, index) => ({
            id:
              index === 0
                ? (template.definition.input_slots[0]?.id ?? "input_1")
                : `input_${index + 1}`,
            label: input.stream.label,
            unit: input.stream.unit ?? null,
          }))
        : template.definition.input_slots;
      const pipeline = await pipelinesApi.create({
        name: name.trim(),
        description: "",
        definition: { ...template.definition, input_slots: slots },
        layout: template.layout,
      });
      onOpen(pipeline.id);
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const pipelines = page?.items;
  return (
    <section className="pl-library" aria-label="Pipeline library">
      <button type="button" className="mn-back" onClick={onBack}>
        <ArrowLeft size={14} />
        Monitoring
      </button>
      <div className="pl-header">
        <div>
          <h2>Pipelines</h2>
          <p className="pl-help">
            Shared designs. Publishing a revision leaves existing monitoring
            runs on their current revision.
          </p>
        </div>
        {canEdit && catalog.authoring_enabled && (
          <button
            type="button"
            className="mn-primary"
            onClick={() => setShowCreate(true)}
          >
            <CopyPlus size={15} />
            New pipeline
          </button>
        )}
      </div>
      {!catalog.authoring_enabled && (
        <p className="pl-warning" role="status">
          Pipeline authoring is disabled for this deployment. Existing designs
          and runs remain available to inspect.
        </p>
      )}
      {error && (
        <p role="alert" className="pl-error">
          {error}
          <button
            type="button"
            onClick={() => {
              setError("");
              setRetry((value) => value + 1);
            }}
          >
            Retry
          </button>
        </p>
      )}
      {showCreate && canEdit && catalog.authoring_enabled && (
        <form
          className="pl-create"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <h3>Start from a template</h3>
          <label className="pl-field">
            <span>Pipeline name</span>
            <input
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <fieldset className="pl-template-grid">
            <legend>Monitoring strategy</legend>
            {catalog.templates.map((template) => (
              <label
                key={template.id}
                className={`pl-template${templateId === template.id ? " is-selected" : ""}`}
              >
                <input
                  type="radio"
                  name="template"
                  value={template.id}
                  checked={templateId === template.id}
                  onChange={() => setTemplateId(template.id)}
                />
                <strong>{template.name}</strong>
                <span>
                  {template.definition.strategy === "adaptive_stream"
                    ? "Learns incrementally from the stream"
                    : "Fits and freezes preprocessing on a baseline"}
                </span>
              </label>
            ))}
          </fieldset>
          {targets.length > 0 && (
            <div className="pl-field">
              <span>Suggest input slots from a source (optional)</span>
              <MonitoringTargetPicker
                targets={targets}
                value={targetId}
                onChange={setTargetId}
              />
              <p className="pl-help">
                Slots use the source's numeric readings. Bindings are reviewed
                before activation.
              </p>
            </div>
          )}
          <div className="pl-actions">
            <button
              type="submit"
              className="mn-primary"
              disabled={busy || !name.trim()}
            >
              {busy ? "Creating…" : "Create draft"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      <div className="pl-library-tools">
        <label className="pl-search">
          <Search size={16} />
          <input
            type="search"
            aria-label="Search pipelines"
            placeholder="Search pipelines…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="pl-check">
          <input
            type="checkbox"
            checked={archived}
            onChange={(event) => setArchived(event.target.checked)}
          />
          Archived designs
        </label>
      </div>
      {!pipelines ? (
        <p role="status">Loading designs…</p>
      ) : !pipelines.length ? (
        <p className="pl-empty">
          {query
            ? "No matching pipelines."
            : archived
              ? "No archived pipelines."
              : "No saved pipelines. Start with a template to create a reusable design."}
        </p>
      ) : (
        <ul className="pl-library-list">
          {pipelines.map((pipeline) => (
            <li key={pipeline.id}>
              <button type="button" onClick={() => onOpen(pipeline.id)}>
                <strong>{pipeline.name}</strong>
                <span>
                  {pipeline.description || "Reusable monitoring design"}
                </span>
                <small>
                  {pipeline.strategy === "adaptive_stream"
                    ? "Adaptive stream"
                    : "Static baseline"}{" "}
                  · {pipeline.revision_count} published{" "}
                  {pipeline.revision_count === 1 ? "revision" : "revisions"}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {page?.next_offset != null && (
        <button disabled={loadingMore} onClick={() => void loadMore()}>
          Load more pipelines
        </button>
      )}
    </section>
  );
}
