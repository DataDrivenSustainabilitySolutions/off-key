import { useState } from "react";
import { Button } from "@/components/ui/button";
import type {
  Catalog,
  CatalogCharger,
  CatalogSnapshot,
  CatalogSource,
} from "@/types/collection";
import { catalogView, type CatalogFilter } from "@/lib/catalog-view";
import { effectivePolicy, pausedPolicy } from "@/types/collection";
import { policyLabel } from "@/lib/catalog-changes";

export const fieldClass =
  "rounded-md border bg-background px-3 py-2 text-sm w-full min-w-0";

export function CatalogEditor({
  catalog,
  snapshot,
  disabled,
  onChange,
  filter,
  showAll,
  selected,
  onSelect,
  onConfigure,
}: {
  catalog: Catalog;
  snapshot: CatalogSnapshot;
  disabled: boolean;
  onChange: (catalog: Catalog) => void;
  filter: CatalogFilter;
  showAll: () => void;
  selected: ReadonlySet<string>;
  onSelect: (id: string, checked: boolean) => void;
  onConfigure: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [brokerSettings, setBrokerSettings] = useState<Set<string>>(new Set());
  const visible = catalogView(catalog, filter);
  const editSource = (id: string, source: CatalogSource) => {
    showAll();
    onChange({
      ...catalog,
      sources: catalog.sources.map((item) => (item.id === id ? source : item)),
    });
  };
  const newCharger = (chargers: CatalogCharger[] = []): CatalogCharger => {
    let localId = 0;
    while (chargers.some((charger) => charger.local_id === String(localId)))
      localId += 1;
    return {
      id: crypto.randomUUID(),
      local_id: String(localId),
      label: "New charger",
      policy: pausedPolicy,
      sensors: [],
    };
  };
  const addBroker = () => {
    const source: CatalogSource = {
      id: crypto.randomUUID(),
      label: "New AmbiBox broker",
      host: "",
      port: 1883,
      verified: false,
      forward_port: null,
      chargers: [newCharger()],
    };
    showAll();
    setBrokerSettings((current) => new Set([...current, source.id]));
    onChange({ ...catalog, sources: [...catalog.sources, source] });
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="outline" disabled={disabled} onClick={addBroker}>
          Add broker
        </Button>
        <p className="text-xs text-muted-foreground">
          New chargers start with collection off.
        </p>
      </div>
      {visible.length === 0 && catalog.sources.length > 0 && (
        <p className="text-sm text-muted-foreground">
          No matching hosts or chargers. Clear the search or change the evidence
          filter.
        </p>
      )}
      {visible.map(({ source, chargers }) => (
        <details
          key={source.id}
          className="overflow-hidden rounded-xl border bg-muted/10 p-4 sm:p-5"
          open={!collapsed.has(source.id)}
          onToggle={(event) => {
            const open = event.currentTarget.open;
            setCollapsed((current) => {
              if (current.has(source.id) === !open) return current;
              const next = new Set(current);
              if (open) next.delete(source.id);
              else next.add(source.id);
              return next;
            });
          }}
        >
          <summary className="cursor-pointer break-words font-medium">
            {source.label}{" "}
            <span className="text-xs font-normal text-muted-foreground">
              · {source.chargers.length} chargers
            </span>
            <span className="mt-1 block break-all text-xs font-normal text-muted-foreground">
              {source.host} ·{" "}
              {source.verified
                ? "Observed broker"
                : "Candidate host · broker not yet observed"}
            </span>
            <span className="mt-2 block text-xs font-normal text-muted-foreground">
              Connection:{" "}
              {snapshot.ingress.sources?.[source.id]?.status ??
                "Not configured"}
            </span>
            {JSON.stringify(source) !==
              JSON.stringify(
                snapshot.catalog.sources.find((item) => item.id === source.id),
              ) && (
              <span className="mt-2 inline-block text-xs text-amber-700 dark:text-amber-300">
                Unsaved changes
              </span>
            )}
          </summary>
          {snapshot.ingress.sources?.[source.id]?.error && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {snapshot.ingress.sources[source.id]!.error}
            </p>
          )}
          <details
            className="mt-4 rounded-lg border bg-card p-3"
            open={brokerSettings.has(source.id)}
            onToggle={(event) => {
              const open = event.currentTarget.open;
              setBrokerSettings((current) => {
                if (current.has(source.id) === open) return current;
                const next = new Set(current);
                if (open) next.add(source.id);
                else next.delete(source.id);
                return next;
              });
            }}
          >
            <summary className="cursor-pointer text-sm text-muted-foreground">
              Broker settings
            </summary>
            <fieldset
              disabled={disabled}
              className="mt-3 grid gap-3 sm:grid-cols-3"
            >
              <label className="text-sm">
                Broker name
                <input
                  className={fieldClass}
                  value={source.label}
                  onChange={(e) =>
                    editSource(source.id, { ...source, label: e.target.value })
                  }
                />
              </label>
              <label className="text-sm">
                Hostname
                <input
                  className={fieldClass}
                  placeholder="charger.ts.net"
                  value={source.host}
                  onChange={(e) =>
                    editSource(source.id, {
                      ...source,
                      host: e.target.value,
                      verified: false,
                    })
                  }
                />
              </label>
              <label className="text-sm">
                Port
                <input
                  className={fieldClass}
                  type="number"
                  min={1}
                  max={65535}
                  value={source.port}
                  onChange={(e) =>
                    editSource(source.id, {
                      ...source,
                      port: Number(e.target.value),
                      verified: false,
                    })
                  }
                />
              </label>
            </fieldset>
          </details>
          {chargers.map((charger) => {
            const editCharger = (next: CatalogCharger) =>
              editSource(source.id, {
                ...source,
                chargers: source.chargers.map((item) =>
                  item.id === charger.id ? next : item,
                ),
              });
            return (
              <section
                key={charger.id}
                aria-label={`Charger ${charger.label}`}
                className="mt-4 rounded-xl border bg-card p-4"
              >
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 size-4 shrink-0"
                      aria-label={`Select ${charger.label} for editing`}
                      disabled={disabled}
                      checked={selected.has(charger.id)}
                      onChange={(event) =>
                        onSelect(charger.id, event.target.checked)
                      }
                    />
                    <div className="min-w-0">
                      <h3 className="break-words font-medium">
                        {charger.label}
                      </h3>
                      {JSON.stringify(charger) !==
                        JSON.stringify(
                          snapshot.catalog.sources
                            .flatMap((source) => source.chargers)
                            .find((item) => item.id === charger.id),
                        ) && (
                        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                          Unsaved changes
                        </p>
                      )}

                      <p className="mt-1 text-xs text-muted-foreground">
                        {
                          charger.sensors.filter(
                            (sensor) =>
                              effectivePolicy(catalog, charger, sensor).mode !==
                              "off",
                          ).length
                        }{" "}
                        of {charger.sensors.length} measurements enabled
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={snapshot.can_edit && disabled}
                    aria-label={
                      snapshot.can_edit
                        ? `Configure ${charger.label}`
                        : `View collection for ${charger.label}`
                    }
                    onClick={() => onConfigure(charger.id)}
                  >
                    {snapshot.can_edit ? "Configure" : "View collection"}
                  </Button>
                </div>
                <details
                  className="rounded-lg border p-3"
                  open={charger.sensors.length === 0}
                >
                  <summary className="cursor-pointer text-sm text-muted-foreground">
                    Charger settings
                  </summary>
                  <fieldset disabled={disabled}>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm">
                        Charger name
                        <input
                          className={fieldClass}
                          value={charger.label}
                          onChange={(e) =>
                            editCharger({ ...charger, label: e.target.value })
                          }
                        />
                      </label>
                      <label className="text-sm">
                        Local charger ID
                        <input
                          className={fieldClass}
                          value={charger.local_id}
                          onChange={(e) =>
                            editCharger({
                              ...charger,
                              local_id: e.target.value,
                              sensors: charger.sensors.map((sensor) => ({
                                ...sensor,
                                upstream_topic: sensor.upstream_topic.replace(
                                  `device/evCharger/${charger.local_id}/`,
                                  `device/evCharger/${e.target.value}/`,
                                ),
                              })),
                            })
                          }
                        />
                      </label>
                    </div>
                    <p className="mt-2 break-all text-xs text-muted-foreground">
                      Application ID: {charger.id}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          let number = 1;
                          while (
                            charger.sensors.some(
                              (sensor) => sensor.key === `sensor-${number}`,
                            )
                          )
                            number += 1;
                          const key = `sensor-${number}`;
                          editCharger({
                            ...charger,
                            sensors: [
                              ...charger.sensors,
                              {
                                key,
                                label: "New sensor",
                                category: "Other",
                                value_type: "number",
                                unit: null,
                                upstream_topic: `device/evCharger/${charger.local_id}/${key}`,
                                policy: pausedPolicy,
                              },
                            ],
                          });
                        }}
                      >
                        Add sensor
                      </Button>
                      <select
                        className={`${fieldClass} max-w-xs`}
                        aria-label="Copy sensor definitions from another charger"
                        value=""
                        onChange={(e) => {
                          const template = catalog.sources
                            .flatMap((item) => item.chargers)
                            .find((item) => item.id === e.target.value);
                          if (template)
                            editCharger({
                              ...charger,
                              sensors: template.sensors.map((sensor) => ({
                                ...sensor,
                                policy: null,
                                upstream_topic: sensor.upstream_topic.replace(
                                  `device/evCharger/${template.local_id}/`,
                                  `device/evCharger/${charger.local_id}/`,
                                ),
                              })),
                              policy: pausedPolicy,
                            });
                        }}
                      >
                        <option value="">Copy sensor definitions…</option>
                        {catalog.sources
                          .flatMap((item) => item.chargers)
                          .filter(
                            (item) =>
                              item.id !== charger.id && item.sensors.length > 0,
                          )
                          .map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label}
                            </option>
                          ))}
                      </select>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          editSource(source.id, {
                            ...source,
                            chargers: source.chargers.filter(
                              (item) => item.id !== charger.id,
                            ),
                          })
                        }
                      >
                        Remove charger
                      </Button>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Copying definitions replaces this charger’s measurements
                      and turns its collection off.
                    </p>
                  </fieldset>
                </details>
                <details className="mt-3" open={charger.sensors.length <= 3}>
                  <summary className="cursor-pointer text-sm font-medium">
                    Measurements{" "}
                    <span className="font-normal text-muted-foreground">
                      ({charger.sensors.length})
                    </span>
                  </summary>
                  {charger.sensors.length === 0 && (
                    <p className="mt-3 text-sm text-muted-foreground">
                      Add measurements in Charger settings.
                    </p>
                  )}
                  {charger.sensors.map((sensor, si) => {
                    const editSensor = (patch: Partial<typeof sensor>) =>
                      editCharger({
                        ...charger,
                        sensors: charger.sensors.map((item, i) =>
                          i === si ? { ...item, ...patch } : item,
                        ),
                      });
                    return (
                      <details key={si} className="mt-3 rounded-lg border p-3">
                        <summary className="cursor-pointer text-sm">
                          <span className="inline-flex w-[calc(100%-1.5rem)] flex-wrap items-center justify-between gap-x-4 gap-y-1 align-middle">
                            <span className="min-w-0 break-words">
                              {sensor.label}{" "}
                              <span className="text-xs text-muted-foreground">
                                · {sensor.category}
                                {sensor.unit ? ` · ${sensor.unit}` : ""}
                              </span>
                            </span>
                            <span
                              className={`rounded-full px-2 py-1 text-xs ${effectivePolicy(catalog, charger, sensor).mode === "off" ? "bg-muted text-muted-foreground" : "bg-primary/10 text-primary"}`}
                            >
                              {policyLabel(
                                effectivePolicy(catalog, charger, sensor),
                              )}
                            </span>
                          </span>
                        </summary>
                        <fieldset
                          disabled={disabled}
                          className="mt-3 grid gap-3 sm:grid-cols-3"
                        >
                          <label className="text-xs">
                            Name
                            <input
                              className={fieldClass}
                              value={sensor.label}
                              onChange={(e) =>
                                editSensor({ label: e.target.value })
                              }
                            />
                          </label>
                          <label className="text-xs">
                            Sensor key
                            <input
                              className={fieldClass}
                              value={sensor.key}
                              onChange={(e) =>
                                editSensor({ key: e.target.value })
                              }
                            />
                          </label>
                          <label className="text-xs">
                            Category
                            <input
                              className={fieldClass}
                              value={sensor.category}
                              onChange={(e) =>
                                editSensor({ category: e.target.value })
                              }
                            />
                          </label>
                          <label className="text-xs sm:col-span-3">
                            Upstream topic
                            <input
                              className={fieldClass}
                              value={sensor.upstream_topic}
                              onChange={(e) =>
                                editSensor({ upstream_topic: e.target.value })
                              }
                            />
                          </label>
                          <label className="text-xs">
                            Value type
                            <select
                              className={fieldClass}
                              value={sensor.value_type}
                              onChange={(e) =>
                                editSensor({
                                  value_type: e.target
                                    .value as typeof sensor.value_type,
                                })
                              }
                            >
                              <option value="number">Number</option>
                              <option value="boolean">Boolean</option>
                              <option value="text">Text</option>
                              <option value="identifier">Identifier</option>
                            </select>
                          </label>
                          <label className="text-xs">
                            Unit (optional)
                            <input
                              className={fieldClass}
                              value={sensor.unit ?? ""}
                              onChange={(e) =>
                                editSensor({ unit: e.target.value || null })
                              }
                            />
                          </label>
                          <Button
                            variant="ghost"
                            onClick={() =>
                              editCharger({
                                ...charger,
                                sensors: charger.sensors.filter(
                                  (_, i) => i !== si,
                                ),
                              })
                            }
                          >
                            Remove sensor
                          </Button>
                        </fieldset>
                      </details>
                    );
                  })}
                </details>
              </section>
            );
          })}
          <fieldset disabled={disabled} className="mt-4 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                showAll();
                editSource(source.id, {
                  ...source,
                  chargers: [...source.chargers, newCharger(source.chargers)],
                });
              }}
            >
              Add charger
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                onChange({
                  ...catalog,
                  sources: catalog.sources.filter(
                    (item) => item.id !== source.id,
                  ),
                })
              }
            >
              Remove broker
            </Button>
          </fieldset>
        </details>
      ))}
    </div>
  );
}
