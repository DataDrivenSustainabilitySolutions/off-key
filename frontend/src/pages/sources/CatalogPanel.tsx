import { useRef, useState } from "react";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { HelpTooltip } from "@/components/HelpTooltip";
import { apiUtils } from "@/lib/api-client";
import type {
  Catalog,
  CatalogSnapshot,
  CollectionPolicy,
} from "@/types/collection";
import {
  catalogView,
  visibleMeasurements,
  type CatalogFilter as Filter,
} from "@/lib/catalog-view";
import { CatalogFilter } from "./CatalogFilter";
import { CatalogEditor } from "./CatalogEditor";
import { fieldClass } from "./InlineField";
import { PolicyPicker } from "./PolicyPicker";
import {
  setMeasurementPolicies,
  validPolicy,
} from "@/lib/collection-selection";

const endpoint = "/v1/sources";

export function CatalogPanel({
  draft,
  snapshot,
  activityAvailable,
  now,
  busy,
  listen,
  listening,
  listenDisabled,
  change,
  task,
  importCatalog,
}: {
  draft: Catalog;
  snapshot: CatalogSnapshot;
  activityAvailable: boolean;
  now: number;
  busy: boolean;
  listen: (sourceId: string) => Promise<void>;
  listening: string | null;
  listenDisabled: boolean;
  change: (catalog: Catalog) => void;
  task: (work: () => Promise<void>) => Promise<void>;
  importCatalog: (catalog: Catalog) => Promise<void>;
}) {
  const [filter, setFilter] = useState<Filter>({
    query: "",
    evidence: "all",
    category: "",
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [policy, setPolicy] = useState<CollectionPolicy>({
    mode: "sample",
    interval_seconds: 10,
  });
  const [history, setHistory] = useState<
    { revision: number; updated_by: string }[]
  >([]);
  const importInput = useRef<HTMLInputElement>(null);
  const disabled = !snapshot.can_edit || busy;
  const measurements = catalogView(draft, filter).flatMap(
    ({ source, chargers }) =>
      chargers.flatMap((charger) =>
        visibleMeasurements(source, charger, filter).map(
          (sensor) => `${charger.id}:${sensor.key}`,
        ),
      ),
  );
  const selectedVisible = new Set(
    measurements.filter((id) => selected.has(id)),
  );
  const categories = [
    ...new Set(
      draft.sources.flatMap((source) =>
        source.chargers.flatMap((charger) =>
          charger.sensors.map((sensor) => sensor.category),
        ),
      ),
    ),
  ].sort();
  const updateFilter = (next: Filter) => {
    setFilter(next);
    setSelected(new Set());
  };

  return (
    <>
      <SectionPanel className="overflow-visible">
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
              Load AmbiBox template
            </Button>
            <p className="text-sm text-muted-foreground">
              Starts with an example broker. Enter your broker details before saving.
            </p>
          </div>
        )}
        <div className="mb-3 flex items-center gap-1 text-xs text-muted-foreground">
          Sensor activity reflects saved settings
          <HelpTooltip label="Sensor activity">
            Recent data means a live reading was received within three sampling
            intervals, with a minimum window of one minute. Original-rate sensors
            use one minute. Retained snapshots do not confirm live data. Sensors
            with collection off are not observed. Listen checks a broker for 20
            seconds and saves collection for sensors sending live data, including
            paused chargers. Save or discard draft changes first. New measurements
            use the catalog default rate, or 10 seconds when the default is Off.
          </HelpTooltip>
        </div>
        <CatalogFilter
          value={filter}
          onChange={updateFilter}
          categories={categories}
        />
        {measurements.length > 0 && (
          <div
            className={`my-4 flex flex-wrap items-center gap-3 rounded-xl p-3 ${selectedVisible.size ? "sticky top-20 z-10 border bg-background/95 shadow-sm backdrop-blur" : "bg-muted/30"}`}
          >
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() =>
                setSelected(
                  selectedVisible.size === measurements.length
                    ? new Set()
                    : new Set(measurements),
                )
              }
            >
              {selectedVisible.size === measurements.length
                ? "Clear selection"
                : `Select ${measurements.length} measurements`}
            </Button>
            {selectedVisible.size > 0 ? (
              <>
                <span className="text-sm" aria-live="polite">
                  {selectedVisible.size} selected
                </span>
                <PolicyPicker
                  label="Collection for selected measurements"
                  value={policy}
                  disabled={disabled}
                  onChange={setPolicy}
                />
                <Button
                  size="sm"
                  disabled={disabled || !validPolicy(policy)}
                  onClick={() =>
                    change(
                      setMeasurementPolicies(draft, selectedVisible, policy),
                    )
                  }
                >
                  Apply to {selectedVisible.size}{" "}
                  {selectedVisible.size === 1 ? "measurement" : "measurements"}
                </Button>
                {selectedVisible.size !== measurements.length && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelected(new Set())}
                  >
                    Clear selection
                  </Button>
                )}
                {!validPolicy(policy) && (
                  <p role="alert" className="text-xs text-destructive">
                    Use whole seconds from 1 to 3600.
                  </p>
                )}
              </>
            ) : null}
          </div>
        )}
        <CatalogEditor
          catalog={draft}
          snapshot={snapshot}
          activityAvailable={activityAvailable}
          now={now}
          disabled={disabled}
          listen={listen}
          listening={listening}
          listenDisabled={listenDisabled}
          onChange={change}
          filter={filter}
          showAll={() =>
            updateFilter({ query: "", evidence: "all", category: "" })
          }
          selected={selectedVisible}
          onSelect={(ids, checked) =>
            setSelected((current) => {
              const next = new Set(current);
              for (const id of ids) {
                if (checked) next.add(id);
                else next.delete(id);
              }
              return next;
            })
          }
        />
        <details className="mt-6 min-w-0 rounded-lg border px-3 py-2 text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            Import and history
          </summary>
          <p className="my-3 text-xs text-muted-foreground">
            Importing or loading a revision replaces your draft catalog and
            collection settings. Save changes to apply.
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
                    updateFilter({ query: "", evidence: "all", category: "" });
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
                    updateFilter({ query: "", evidence: "all", category: "" });
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
    </>
  );
}
