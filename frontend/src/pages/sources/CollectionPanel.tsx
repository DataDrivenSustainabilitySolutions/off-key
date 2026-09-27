import { useState } from "react";
import { Link } from "react-router-dom";
import { SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import type {
  Catalog,
  CatalogCharger,
  CatalogSnapshot,
  CollectionPolicy,
} from "@/types/collection";
import { effectivePolicy, pausedPolicy } from "@/types/collection";
import { fieldClass } from "./CatalogEditor";
import { PolicyPicker } from "./PolicyPicker";
import { catalogView, type CatalogFilter as Filter } from "@/lib/catalog-view";
import { policyLabel } from "@/lib/catalog-changes";
import { CatalogFilter } from "./CatalogFilter";
import { LatestState } from "./LatestState";

export function CollectionPanel({
  draft,
  snapshot,
  busy,
  change,
}: {
  draft: Catalog;
  snapshot: CatalogSnapshot;
  busy: boolean;
  change: (catalog: Catalog) => void;
}) {
  const [filter, setFilter] = useState<Filter>({ query: "", evidence: "all" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState("all");
  const [bulkPolicy, setBulkPolicy] = useState<CollectionPolicy>({
    mode: "sample",
    interval_seconds: 10,
  });
  const [stateCharger, setStateCharger] = useState<string | null>(null);
  const chargers = draft.sources.flatMap((source) => source.chargers);
  const categories = [
    ...new Set(
      chargers.flatMap((charger) =>
        charger.sensors.map((sensor) => sensor.category),
      ),
    ),
  ].sort();
  const visible = catalogView(draft, filter);
  const visibleChargers = visible.flatMap((item) => item.chargers);
  const selectedVisible = new Set(
    visibleChargers
      .filter((charger) => selected.has(charger.id))
      .map((charger) => charger.id),
  );
  const allVisibleSelected =
    visibleChargers.length > 0 &&
    selectedVisible.size === visibleChargers.length;
  const selectedCount = chargers.filter((charger) =>
    selected.has(charger.id),
  ).length;
  const editCharger = (
    chargerId: string,
    edit: (charger: CatalogCharger) => CatalogCharger,
  ) =>
    change({
      ...draft,
      sources: draft.sources.map((source) => ({
        ...source,
        chargers: source.chargers.map((charger) =>
          charger.id === chargerId ? edit(charger) : charger,
        ),
      })),
    });
  const bulk = (policy: CollectionPolicy) =>
    change({
      ...draft,
      sources: draft.sources.map((source) => ({
        ...source,
        chargers: source.chargers.map((charger) => {
          if (!selectedVisible.has(charger.id)) return charger;
          return category === "all"
            ? {
                ...charger,
                policy,
                sensors: charger.sensors.map((sensor) => ({
                  ...sensor,
                  policy: null,
                })),
              }
            : {
                ...charger,
                sensors: charger.sensors.map((sensor) =>
                  sensor.category === category ? { ...sensor, policy } : sensor,
                ),
              };
        }),
      })),
    });

  return (
    <>
      <SectionPanel
        title="Collection defaults"
        description="Sampling keeps the newest observation within each interval. A quiet stream produces no repeated or synthetic measurements."
      >
        <PolicyPicker
          value={draft.default_policy}
          label="Fleet default"
          disabled={!snapshot.can_edit || busy}
          onChange={(policy) =>
            policy && change({ ...draft, default_policy: policy })
          }
        />
        <p className="mt-3 text-xs text-muted-foreground">
          New chargers are paused until selected. Original-rate state values
          update at most once per second. EMQX may still receive unselected
          sensors while another sensor on that broker is selected.
        </p>
        <div className="mt-5 border-t pt-4">
          <CatalogFilter value={filter} onChange={setFilter} />
          <p className="mt-3 text-xs text-muted-foreground">
            Showing {visibleChargers.length} of {chargers.length} chargers. Bulk
            changes affect only visible selected chargers and the chosen sensor
            category.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-sm">
            {selectedVisible.size} visible chargers selected ·{" "}
            {selectedCount - selectedVisible.size} hidden selections
          </span>
          <select
            aria-label="Bulk sensor category"
            className={`${fieldClass} max-w-48`}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">All categories</option>
            {categories.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <PolicyPicker
            label="Bulk collection policy"
            value={bulkPolicy}
            onChange={(policy) => policy && setBulkPolicy(policy)}
          />
          <Button
            variant="outline"
            disabled={!snapshot.can_edit || busy || selectedVisible.size === 0}
            onClick={() => bulk(bulkPolicy)}
          >
            Set for visible selected
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              setSelected((current) => {
                const next = new Set(current);
                for (const charger of visibleChargers) {
                  if (allVisibleSelected) next.delete(charger.id);
                  else next.add(charger.id);
                }
                return next;
              })
            }
            disabled={visibleChargers.length === 0}
          >
            {allVisibleSelected
              ? "Clear visible selection"
              : "Select visible chargers"}
          </Button>
        </div>
      </SectionPanel>
      {visible.map(({ source, chargers: shownChargers }) => (
        <SectionPanel
          key={source.id}
          title={source.label}
          description={`${source.host}:${source.port} · ${source.verified ? "Observed broker" : "Candidate host · broker not yet observed"} · ${snapshot.ingress.sources?.[source.id]?.status ?? "Not applied"}`}
        >
          {snapshot.ingress.sources?.[source.id]?.error && (
            <p className="mb-3 text-sm text-destructive">
              {snapshot.ingress.sources?.[source.id]?.error}
            </p>
          )}
          {shownChargers.map((charger) => (
            <div key={charger.id} className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <label className="flex items-center gap-3 font-medium">
                  <input
                    type="checkbox"
                    checked={selected.has(charger.id)}
                    onChange={(e) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (e.target.checked) next.add(charger.id);
                        else next.delete(charger.id);
                        return next;
                      })
                    }
                  />
                  {charger.label}
                </label>
                <PolicyPicker
                  label={`${charger.label} default`}
                  inherited
                  value={charger.policy}
                  disabled={!snapshot.can_edit || busy}
                  onChange={(policy) =>
                    editCharger(charger.id, (item) => ({
                      ...item,
                      policy,
                    }))
                  }
                />
              </div>
              <details>
                <summary className="cursor-pointer text-sm text-muted-foreground">
                  {
                    charger.sensors.filter(
                      (sensor) =>
                        effectivePolicy(draft, charger, sensor).mode !== "off",
                    ).length
                  }{" "}
                  / {charger.sensors.length} sensors selected · adjust
                  individual sensors
                </summary>
                <div className="mt-3 divide-y">
                  {charger.sensors.map((sensor) => (
                    <div
                      key={sensor.key}
                      className="flex flex-wrap items-center justify-between gap-3 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium">
                          {sensor.label} {sensor.unit ? `(${sensor.unit})` : ""}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {sensor.category} · {sensor.value_type} · effective:{" "}
                          {policyLabel(effectivePolicy(draft, charger, sensor))}
                        </p>
                      </div>
                      <PolicyPicker
                        label={`${charger.label} ${sensor.label}`}
                        inherited
                        value={sensor.policy}
                        disabled={!snapshot.can_edit || busy}
                        onChange={(policy) =>
                          editCharger(charger.id, (item) => ({
                            ...item,
                            sensors: item.sensors.map((entry) =>
                              entry.key === sensor.key
                                ? { ...entry, policy }
                                : entry,
                            ),
                          }))
                        }
                      />
                    </div>
                  ))}
                </div>
              </details>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!snapshot.can_edit || busy}
                  onClick={() =>
                    editCharger(charger.id, (item) => ({
                      ...item,
                      policy: pausedPolicy,
                      sensors: item.sensors.map((sensor) => ({
                        ...sensor,
                        policy: null,
                      })),
                    }))
                  }
                >
                  Pause all sensors
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setStateCharger(
                      stateCharger === charger.id ? null : charger.id,
                    )
                  }
                >
                  Latest observations
                </Button>
                <Button size="sm" variant="ghost" asChild>
                  <Link to={`/details/${charger.id}`}>View telemetry</Link>
                </Button>
              </div>
              {stateCharger === charger.id && (
                <LatestState chargerId={charger.id} />
              )}
            </div>
          ))}
        </SectionPanel>
      ))}
      {visible.length === 0 && draft.sources.length > 0 && (
        <p className="text-sm text-muted-foreground">
          No matching hosts or chargers. Clear the search or change the evidence
          filter.
        </p>
      )}
      {draft.sources.length === 0 && (
        <SectionPanel title="No catalog yet">
          <p className="text-sm text-muted-foreground">
            Open Catalog to load the AmbiBox inventory or add a broker.
            Collection stays idle until you select sensors and apply the
            configuration.
          </p>
        </SectionPanel>
      )}
    </>
  );
}
