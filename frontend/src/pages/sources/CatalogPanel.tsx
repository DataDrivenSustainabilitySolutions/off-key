import { useRef, useState } from "react";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import type { Catalog, CatalogSnapshot } from "@/types/collection";
import { catalogView, type CatalogFilter as Filter } from "@/lib/catalog-view";
import { CatalogFilter } from "./CatalogFilter";
import { CatalogEditor, fieldClass } from "./CatalogEditor";
import { CollectionEditor } from "./CollectionEditor";

const endpoint = "/v1/sources";

export function CatalogPanel({
  draft,
  snapshot,
  busy,
  conflict,
  change,
  task,
  importCatalog,
}: {
  draft: Catalog;
  snapshot: CatalogSnapshot;
  busy: boolean;
  conflict: boolean;
  change: (catalog: Catalog) => void;
  task: (work: () => Promise<void>) => Promise<void>;
  importCatalog: (catalog: Catalog) => Promise<void>;
}) {
  const [filter, setFilter] = useState<Filter>({ query: "", evidence: "all" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<Set<string> | null>(null);
  const [history, setHistory] = useState<
    { revision: number; updated_by: string }[]
  >([]);
  const importInput = useRef<HTMLInputElement>(null);
  const disabled = !snapshot.can_edit || busy;
  const chargers = catalogView(draft, filter).flatMap(
    ({ chargers }) => chargers,
  );
  const selectedVisible = new Set(
    chargers
      .filter((charger) => selected.has(charger.id))
      .map((charger) => charger.id),
  );
  const updateFilter = (next: Filter) => {
    setFilter(next);
    setSelected(new Set());
  };

  return (
    <>
      <SectionPanel
        title="Your catalog"
        description="Brokers → chargers → measurements"
      >
        {draft.sources.length === 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              disabled={disabled}
              onClick={() =>
                void task(async () =>
                  change(
                    await apiUtils.get<Catalog>(`${endpoint}/ambibox-template`),
                  ),
                )
              }
            >
              Load AmbiBox inventory
            </Button>
          </div>
        )}
        <CatalogFilter value={filter} onChange={updateFilter} />
        {chargers.length > 0 && (
          <div className="my-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/40 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                variant="outline"
                disabled={disabled}
                onClick={() =>
                  setSelected(
                    selectedVisible.size === chargers.length
                      ? new Set()
                      : new Set(chargers.map((charger) => charger.id)),
                  )
                }
              >
                {selectedVisible.size === chargers.length
                  ? "Clear selection"
                  : "Select shown chargers"}
              </Button>
              <p className="text-sm" aria-live="polite">
                {selectedVisible.size
                  ? `${selectedVisible.size} selected for editing`
                  : `${chargers.length} chargers shown`}
              </p>
            </div>
            <Button
              size="sm"
              disabled={disabled || selectedVisible.size === 0}
              onClick={() => setEditing(selectedVisible)}
            >
              Configure selected
            </Button>
          </div>
        )}
        <CatalogEditor
          catalog={draft}
          snapshot={snapshot}
          disabled={disabled}
          onChange={change}
          filter={filter}
          showAll={() => updateFilter({ query: "", evidence: "all" })}
          selected={selectedVisible}
          onSelect={(id, checked) =>
            setSelected((current) => {
              const next = new Set(current);
              if (checked) next.add(id);
              else next.delete(id);
              return next;
            })
          }
          onConfigure={(id) => setEditing(new Set([id]))}
        />
        <details className="mt-6 min-w-0 rounded-lg border px-3 py-2 text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            Import and history
          </summary>
          <p className="my-3 text-xs text-muted-foreground">
            Importing or loading a revision replaces both definitions and
            collection settings in your unsaved changes. Save changes to apply
            them.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              ref={importInput}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file)
                  void task(async () => {
                    if (file.size > 1024 * 1024)
                      throw new Error("Catalog files must be under 1 MB");
                    await importCatalog(JSON.parse(await file.text()));
                    updateFilter({ query: "", evidence: "all" });
                  });
              }}
            />
            <Button
              variant="outline"
              disabled={disabled}
              onClick={() => importInput.current?.click()}
            >
              Import catalog
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void task(async () =>
                  setHistory(await apiUtils.get(`${endpoint}/revisions`)),
                )
              }
            >
              Revision history
            </Button>
            {history.length > 0 && (
              <select
                className={`${fieldClass} max-w-xs`}
                aria-label="Load historical catalog into draft"
                value=""
                disabled={disabled}
                onChange={(event) => {
                  const revision = event.target.value;
                  void task(async () => {
                    change(
                      await apiUtils.get<Catalog>(
                        `${endpoint}/revisions/${revision}`,
                      ),
                    );
                    updateFilter({ query: "", evidence: "all" });
                  });
                }}
              >
                <option value="">Load a revision…</option>
                {history.map((item) => (
                  <option key={item.revision} value={item.revision}>
                    Revision {item.revision} · {item.updated_by}
                  </option>
                ))}
              </select>
            )}
          </div>
        </details>
      </SectionPanel>
      {editing && (
        <CollectionEditor
          catalog={draft}
          chargerIds={editing}
          disabled={disabled}
          conflict={conflict}
          readOnly={!snapshot.can_edit}
          onClose={() => setEditing(null)}
          onSave={(catalog) => {
            change(catalog);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
