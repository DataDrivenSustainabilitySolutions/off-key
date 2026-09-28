import { useState } from "react";
import { Link } from "react-router-dom";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { catalogView, type CatalogFilter as Filter } from "@/lib/catalog-view";
import { configureCollection } from "@/lib/collection-selection";
import type { Catalog, CatalogSnapshot } from "@/types/collection";
import { effectivePolicy } from "@/types/collection";
import { CatalogFilter } from "./CatalogFilter";
import { CollectionEditor } from "./CollectionEditor";
import { LatestState } from "./LatestState";

export function CollectionPanel({
  draft,
  snapshot,
  busy,
  conflict,
  change,
  onCatalog,
  onLoadInventory,
}: {
  draft: Catalog;
  snapshot: CatalogSnapshot;
  busy: boolean;
  conflict: boolean;
  change: (catalog: Catalog) => void;
  onCatalog: () => void;
  onLoadInventory: () => void;
}) {
  const [filter, setFilter] = useState<Filter>({ query: "", evidence: "all" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<Set<string> | null>(null);
  const [stateCharger, setStateCharger] = useState<string | null>(null);
  const disabled = !snapshot.can_edit || busy;
  const visible = catalogView(draft, filter);
  const chargers = visible.flatMap(({ source, chargers }) =>
    chargers.map((charger) => ({ source, charger })),
  );
  const selectedVisible = new Set(
    chargers
      .filter(({ charger }) => selected.has(charger.id))
      .map(({ charger }) => charger.id),
  );
  const total = draft.sources.reduce(
    (count, source) => count + source.chargers.length,
    0,
  );

  if (total === 0)
    return (
      <SectionPanel
        title="Start collecting data"
        description="Load the prepared AmbiBox inventory, then choose the chargers and measurements you need."
      >
        <p className="mb-5 text-sm text-muted-foreground">
          Loading a catalog does not start collection. All new chargers start
          paused.
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            disabled={disabled || draft.sources.length > 0}
            onClick={onLoadInventory}
          >
            Load AmbiBox inventory
          </Button>
          <Button variant="outline" onClick={onCatalog}>
            Build or import a catalog
          </Button>
        </div>
      </SectionPanel>
    );

  return (
    <>
      <SectionPanel
        title="Choose chargers"
        description="Configure a charger, or select several to edit together."
      >
        <CatalogFilter
          value={filter}
          onChange={(next) => {
            setFilter(next);
            setSelected(new Set());
          }}
        />
        <div className="my-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/40 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={disabled || chargers.length === 0}
              onClick={() =>
                setSelected(
                  selectedVisible.size === chargers.length
                    ? new Set()
                    : new Set(chargers.map(({ charger }) => charger.id)),
                )
              }
            >
              {chargers.length > 0 && selectedVisible.size === chargers.length
                ? "Clear selection"
                : "Select shown chargers"}
            </Button>
            <p className="text-sm" aria-live="polite">
              {selectedVisible.size > 0
                ? `${selectedVisible.size} selected for editing`
                : `${chargers.length} of ${total} chargers shown`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={disabled || selectedVisible.size === 0}
              onClick={() =>
                change(configureCollection(draft, selectedVisible, new Map()))
              }
            >
              Pause selected
            </Button>
            <Button
              size="sm"
              disabled={disabled || selectedVisible.size === 0}
              onClick={() => setEditing(selectedVisible)}
            >
              Configure selected
            </Button>
          </div>
        </div>
        <div className="divide-y rounded-xl border">
          {chargers.map(({ source, charger }) => {
            const count = charger.sensors.filter(
              (sensor) =>
                effectivePolicy(draft, charger, sensor).mode !== "off",
            ).length;
            const saved = snapshot.catalog.sources
              .flatMap((item) => item.chargers)
              .find((item) => item.id === charger.id);
            const unsaved = JSON.stringify(saved) !== JSON.stringify(charger);
            const connection = snapshot.ingress.sources?.[source.id];
            return (
              <div key={charger.id} className="space-y-3 p-4">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                  <div className="flex min-w-0 items-start gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 size-4 shrink-0"
                      aria-label={`Select ${charger.label} for editing`}
                      disabled={disabled}
                      checked={selected.has(charger.id)}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setSelected((current) => {
                          const next = new Set(current);
                          if (checked) next.add(charger.id);
                          else next.delete(charger.id);
                          return next;
                        });
                      }}
                    />
                    <div className="min-w-0">
                      <p className="break-words font-medium">{charger.label}</p>
                      <p className="mt-1 break-all text-xs text-muted-foreground">
                        {source.host} ·{" "}
                        {source.verified ? "Observed broker" : "Candidate host"}
                      </p>
                      <p className="mt-2 text-sm">
                        {count
                          ? `${count} of ${charger.sensors.length} measurements`
                          : "Paused"}
                        {unsaved && (
                          <span className="ml-2 text-xs font-medium text-amber-700 dark:text-amber-300">
                            Draft change
                          </span>
                        )}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Connection: {connection?.status ?? "Not configured"}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2 pl-7 sm:pl-0">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={snapshot.can_edit && busy}
                      aria-label={
                        snapshot.can_edit
                          ? `Configure ${charger.label}`
                          : `View collection for ${charger.label}`
                      }
                      onClick={() => setEditing(new Set([charger.id]))}
                    >
                      {snapshot.can_edit ? "Configure" : "View collection"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!saved}
                      onClick={() =>
                        setStateCharger(
                          stateCharger === charger.id ? null : charger.id,
                        )
                      }
                      aria-expanded={stateCharger === charger.id}
                    >
                      Latest values
                    </Button>
                    {saved && (
                      <Button size="sm" variant="ghost" asChild>
                        <Link to={`/details/${charger.id}`}>
                          View telemetry
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
                {connection?.error && (
                  <p role="alert" className="text-sm text-destructive">
                    {connection.error}
                  </p>
                )}
                {stateCharger === charger.id && (
                  <LatestState chargerId={charger.id} />
                )}
              </div>
            );
          })}
          {chargers.length === 0 && (
            <p className="p-6 text-sm text-muted-foreground">
              No chargers match this search. Clear the search or change the
              broker filter.
            </p>
          )}
        </div>
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
