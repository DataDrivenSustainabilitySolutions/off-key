import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";

import {
  MetricCard,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { NavigationBar } from "@/components/NavigationBar";
import { Button } from "@/components/ui/button";
import { apiUtils } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import type {
  Catalog,
  CatalogCharger,
  CatalogPreview,
  CatalogSnapshot,
  CollectionPolicy,
} from "@/types/collection";
import {
  effectivePolicy,
  pausedPolicy,
  runtimeLabel,
} from "@/types/collection";
import { CatalogEditor, fieldClass } from "./sources/CatalogEditor";
import { PolicyPicker } from "./sources/PolicyPicker";

const endpoint = "/v1/sources";
type SensorState = {
  sensor_key: string;
  value: unknown;
  received_at: string;
  is_snapshot: boolean;
};

function LatestState({ chargerId }: { chargerId: string }) {
  const [states, setStates] = useState<SensorState[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const refresh = () =>
      apiUtils
        .get<SensorState[]>(`${endpoint}/state/${chargerId}`)
        .then((data) => {
          if (active) {
            setStates(data);
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(getErrorMessage(e));
        });
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [chargerId]);
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-3">
      {error && <p role="alert">{error}</p>}
      {!error && states.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No observations collected yet.
        </p>
      )}
      {states.map((state) => (
        <div
          key={state.sensor_key}
          className="rounded-lg bg-muted/50 p-3 text-xs"
        >
          <p className="break-all font-medium">
            {state.sensor_key}: {String(state.value)}
          </p>
          <p className="mt-1 text-muted-foreground">
            {state.is_snapshot
              ? "Snapshot · measurement age unknown"
              : "Observed"}{" "}
            · {new Date(state.received_at).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}

export default function DataSources() {
  const [snapshot, setSnapshot] = useState<CatalogSnapshot | null>(null);
  const [draft, setDraft] = useState<Catalog | null>(null);
  const [baseRevision, setBaseRevision] = useState(0);
  const [tab, setTab] = useState<"collection" | "catalog">("collection");
  const [preview, setPreview] = useState<CatalogPreview | null>(null);
  const [pauseMonitors, setPauseMonitors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState("all");
  const [bulkPolicy, setBulkPolicy] = useState<CollectionPolicy>({
    mode: "sample",
    interval_seconds: 10,
  });
  const [stateCharger, setStateCharger] = useState<string | null>(null);
  const [history, setHistory] = useState<
    { revision: number; updated_by: string }[]
  >([]);
  const initialized = useRef(false);
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const first = !initialized.current;
        const data = await apiUtils.get<CatalogSnapshot>(
          first ? endpoint : `${endpoint}/status`,
        );
        if (!active) return;
        setSnapshot((current) => {
          if (current && current.revision > data.revision) return current;
          if (first) return data;
          return current && {
            ...current,
            revision: data.revision,
            ingress: data.ingress,
            collection: data.collection,
          };
        });
        if (!initialized.current) {
          initialized.current = true;
          setDraft(data.catalog);
          setBaseRevision(data.revision);
        }
      } catch (e) {
        if (active) setError(getErrorMessage(e));
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const change = (catalog: Catalog) => {
    setDraft(catalog);
    setPreview(null);
    setPauseMonitors(false);
    setError("");
  };
  const task = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const validate = async (catalog: Catalog) => {
    const result = await apiUtils.post<CatalogPreview>(`${endpoint}/preview`, {
      expected_revision: baseRevision,
      catalog,
    });
    setPreview(result);
    setDraft(result.catalog);
    setPauseMonitors(false);
  };
  const exportCatalog = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "ambibox-catalog.json";
    link.click();
    URL.revokeObjectURL(url);
  };
  const importFile = (file?: File) => {
    if (!file) return;
    void task(async () => {
      if (file.size > 1024 * 1024)
        throw new Error("Catalog files must be under 1 MB");
      await validate(JSON.parse(await file.text()));
      setTab("catalog");
    });
  };

  if (!snapshot || !draft)
    return (
      <>
        <NavigationBar />
        <PageShell>
          <PageHeader title="Data sources" />
          <p role={error ? "alert" : "status"}>{error || "Loading catalog…"}</p>
        </PageShell>
      </>
    );
  const chargers = draft.sources.flatMap((source) => source.chargers);
  const categories = [
    ...new Set(
      chargers.flatMap((charger) =>
        charger.sensors.map((sensor) => sensor.category),
      ),
    ),
  ].sort();
  const sensors = chargers.flatMap((charger) =>
    charger.sensors.map((sensor) => ({
      sensor,
      policy: effectivePolicy(draft, charger, sensor),
    })),
  );
  const activeCount = sensors.filter(
    (item) => item.policy.mode !== "off",
  ).length;
  const changed = JSON.stringify(draft) !== JSON.stringify(snapshot.catalog);
  const conflict = snapshot.revision !== baseRevision;
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
          if (!selected.has(charger.id)) return charger;
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
      <NavigationBar />
      <PageShell>
        <PageHeader
          title="Data sources"
          eyebrow="AmbiBox"
          description="Choose chargers and measurements to collect. Saving applies the selection before telemetry reaches storage and monitoring."
          actions={
            <>
              <Button variant="outline" onClick={exportCatalog}>
                Export catalog
              </Button>
              {snapshot.can_edit && (
                <Button
                  disabled={busy || conflict}
                  onClick={() => void task(() => validate(draft))}
                >
                  Review changes
                </Button>
              )}
            </>
          }
        />
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive p-4 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        {conflict && (
          <p role="alert" className="rounded-lg border p-4 text-sm">
            Someone saved a newer catalog. Export your draft if needed, then
            reload to continue.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-4">
          <MetricCard
            label="Catalog"
            value={chargers.length}
            helper={`${draft.sources.length} brokers · ${draft.sources.filter((source) => !source.verified).length} unverified`}
          />
          <MetricCard
            label="Selected sensors"
            value={activeCount}
            helper={`of ${sensors.length} in this draft`}
          />
          <MetricCard
            label="Collection"
            value={
              <span className="text-base">
                {runtimeLabel(snapshot.collection, snapshot.revision)}
              </span>
            }
            helper={`Saved revision ${snapshot.revision}${changed ? " · unsaved edits" : ""}`}
          />
          <MetricCard
            label="Broker routes"
            value={
              <span className="text-base">
                {runtimeLabel(snapshot.ingress, snapshot.revision)}
              </span>
            }
            helper={
              snapshot.ingress.error ??
              `${Object.values(snapshot.ingress.sources ?? {}).filter((source) => source.status === "connected").length} connected`
            }
          />
        </div>
        {(snapshot.collection.error || snapshot.ingress.error) && (
          <p role="alert" className="text-sm text-destructive">
            {snapshot.collection.error ?? snapshot.ingress.error}
          </p>
        )}
        {preview && (
          <SectionPanel
            title="Review collection changes"
            description="Nothing changes until you apply this revision."
          >
            <p className="text-sm">
              {preview.selected_sensors} selected sensors. Sampled numeric
              history: up to{" "}
              {preview.sampled_rows_per_day_ceiling.toLocaleString()} rows per
              day when every stream reports continuously.{" "}
              {preview.original_rate_sensors} numeric sensors use original rate,
              with no fixed daily bound.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Text, identifiers, and booleans keep only their latest state.
              Retained snapshots do not create fresh numeric history.
            </p>
            {preview.affected_monitors.length > 0 && (
              <label className="mt-4 flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={pauseMonitors}
                  onChange={(e) => setPauseMonitors(e.target.checked)}
                />
                Pause affected monitors:{" "}
                {preview.affected_monitors
                  .map((monitor) => monitor.name)
                  .join(", ")}
                . Restart them with fresh calibration after this change.
              </label>
            )}
            <Button
              className="mt-4"
              disabled={
                busy ||
                conflict ||
                (preview.affected_monitors.length > 0 && !pauseMonitors)
              }
              onClick={() =>
                void task(async () => {
                  const result = await apiUtils.put<CatalogSnapshot>(endpoint, {
                    expected_revision: preview.revision,
                    catalog: preview.catalog,
                    pause_affected_monitors: pauseMonitors,
                  });
                  setSnapshot({ ...result, can_edit: snapshot.can_edit });
                  setDraft(result.catalog);
                  setBaseRevision(result.revision);
                  setPreview(null);
                  toast.success(
                    "Configuration saved. Workers are applying it.",
                  );
                })
              }
            >
              Apply collection
            </Button>
          </SectionPanel>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={tab === "collection" ? "default" : "outline"}
            onClick={() => setTab("collection")}
          >
            Collection
          </Button>
          <Button
            variant={tab === "catalog" ? "default" : "outline"}
            onClick={() => setTab("catalog")}
          >
            Catalog
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void task(async () => {
                const saved = await apiUtils.get<CatalogSnapshot>(endpoint);
                setSnapshot(saved);
                change(saved.catalog);
                setBaseRevision(saved.revision);
              })
            }
          >
            Reload saved catalog
          </Button>
          {!snapshot.can_edit && (
            <span className="text-sm text-muted-foreground">
              View only · an administrator can change collection
            </span>
          )}
        </div>
        {tab === "catalog" ? (
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
                disabled={!snapshot.can_edit || busy}
                onClick={() => importInput.current?.click()}
              >
                Import catalog
              </Button>
              <Button
                variant="outline"
                disabled={
                  !snapshot.can_edit || busy || draft.sources.length > 0
                }
                onClick={() =>
                  void task(async () => {
                    change(
                      await apiUtils.get<Catalog>(
                        `${endpoint}/ambibox-template`,
                      ),
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
                  disabled={!snapshot.can_edit || busy}
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
              The development inventory contains 31 visible hosts. Four brokers
              were observed; the remaining sensor definitions are assumptions to
              verify. All start paused.
            </p>
            <fieldset disabled={!snapshot.can_edit || busy}>
              <CatalogEditor catalog={draft} onChange={change} />
            </fieldset>
          </SectionPanel>
        ) : (
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
                New chargers are paused until selected. Original-rate state
                values update at most once per second. EMQX may still receive
                unselected sensors while another sensor on that broker is
                selected.
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-3 border-t pt-4">
                <span className="text-sm">
                  {selected.size} chargers selected
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
                  disabled={!snapshot.can_edit || busy || selected.size === 0}
                  onClick={() => bulk(bulkPolicy)}
                >
                  Set for selected
                </Button>
                <Button
                  variant="ghost"
                  onClick={() =>
                    setSelected(
                      new Set(
                        selected.size === chargers.length
                          ? []
                          : chargers.map((charger) => charger.id),
                      ),
                    )
                  }
                >
                  {selected.size === chargers.length
                    ? "Clear selection"
                    : "Select all"}
                </Button>
              </div>
            </SectionPanel>
            {draft.sources.map((source) => (
              <SectionPanel
                key={source.id}
                title={source.label}
                description={`${source.host}:${source.port} · ${source.verified ? "Observed broker" : "Unverified catalog"} · ${snapshot.ingress.sources?.[source.id]?.status ?? "Not applied"}`}
              >
                {snapshot.ingress.sources?.[source.id]?.error && (
                  <p className="mb-3 text-sm text-destructive">
                    {snapshot.ingress.sources?.[source.id]?.error}
                  </p>
                )}
                {source.chargers.map((charger) => (
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
                              effectivePolicy(draft, charger, sensor).mode !==
                              "off",
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
                                {sensor.label}{" "}
                                {sensor.unit ? `(${sensor.unit})` : ""}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {sensor.category} · {sensor.value_type} ·
                                effective:{" "}
                                {effectivePolicy(draft, charger, sensor).mode}
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
                        <Link to={`/details/${charger.id}`}>
                          View telemetry
                        </Link>
                      </Button>
                    </div>
                    {stateCharger === charger.id && (
                      <LatestState chargerId={charger.id} />
                    )}
                  </div>
                ))}
              </SectionPanel>
            ))}
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
        )}
        <p className="text-xs text-muted-foreground">
          Collection counters: {snapshot.collection.records_written ?? 0}{" "}
          numeric rows written since worker start ·{" "}
          {snapshot.collection.counters?.overload_dropped ?? 0} observations
          dropped due to queue limits ·{" "}
          {snapshot.collection.counters?.invalid ?? 0} invalid observations
          rejected.
        </p>
      </PageShell>
    </>
  );
}
