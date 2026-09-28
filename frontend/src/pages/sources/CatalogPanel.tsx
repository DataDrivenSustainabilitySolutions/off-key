import { useRef, useState } from "react";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import type { Catalog } from "@/types/collection";
import type { CatalogFilter as Filter } from "@/lib/catalog-view";
import { CatalogFilter } from "./CatalogFilter";
import { CatalogEditor, fieldClass } from "./CatalogEditor";

const endpoint = "/v1/sources";

export function CatalogPanel({
  draft,
  canEdit,
  busy,
  change,
  task,
  validate,
}: {
  draft: Catalog;
  canEdit: boolean;
  busy: boolean;
  change: (catalog: Catalog) => void;
  task: (work: () => Promise<void>) => Promise<void>;
  validate: (catalog: Catalog) => Promise<void>;
}) {
  const [filter, setFilter] = useState<Filter>({ query: "", evidence: "all" });
  const [history, setHistory] = useState<
    { revision: number; updated_by: string }[]
  >([]);
  const importInput = useRef<HTMLInputElement>(null);
  const importFile = (file?: File) => {
    if (!file) return;
    void task(async () => {
      if (file.size > 1024 * 1024)
        throw new Error("Catalog files must be under 1 MB");
      await validate(JSON.parse(await file.text()));
    });
  };
  return (
    <SectionPanel
      title="Build your catalog"
      description="Add definitions manually, import a JSON catalog, or start from the development inventory."
    >
      <div className="mb-5 flex flex-wrap gap-2">
        <input
          ref={importInput}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            importFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          variant="outline"
          disabled={!canEdit || busy}
          onClick={() => importInput.current?.click()}
        >
          Import catalog
        </Button>
        <Button
          variant="outline"
          disabled={!canEdit || busy || draft.sources.length > 0}
          onClick={() =>
            void task(async () => {
              change(
                await apiUtils.get<Catalog>(`${endpoint}/ambibox-template`),
              );
            })
          }
        >
          Load AmbiBox inventory
        </Button>
        <Button
          variant="ghost"
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
            disabled={!canEdit || busy}
            onChange={(e) =>
              void task(async () =>
                change(
                  await apiUtils.get<Catalog>(
                    `${endpoint}/revisions/${e.target.value}`,
                  ),
                ),
              )
            }
          >
            <option value="">Load a revision into the draft…</option>
            {history.map((item) => (
              <option value={item.revision} key={item.revision}>
                Revision {item.revision} · {item.updated_by}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        This draft contains{" "}
        {draft.sources.filter((source) => source.verified).length} observed
        brokers and {draft.sources.filter((source) => !source.verified).length}{" "}
        candidate hosts. Candidate hosts and their sensor definitions need
        verification. Loading the development inventory starts collection
        paused.
      </p>
      <div className="mb-5">
        <CatalogFilter value={filter} onChange={setFilter} />
        <p className="mt-2 text-xs text-muted-foreground">
          Editing clears the filters to keep your entry visible.
        </p>
      </div>
      <fieldset disabled={!canEdit || busy}>
        <CatalogEditor
          catalog={draft}
          onChange={change}
          filter={filter}
          showAll={() => setFilter({ query: "", evidence: "all" })}
        />
      </fieldset>
    </SectionPanel>
  );
}
