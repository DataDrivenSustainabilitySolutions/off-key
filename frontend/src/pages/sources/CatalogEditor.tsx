import { useState } from "react";
import { Button } from "@/components/ui/button";
import type {
  Catalog,
  CatalogCharger,
  CatalogSource,
} from "@/types/collection";
import { catalogView, type CatalogFilter } from "@/lib/catalog-view";
import { pausedPolicy } from "@/types/collection";

export const fieldClass =
  "rounded-md border bg-background px-3 py-2 text-sm w-full min-w-0";

export function CatalogEditor({
  catalog,
  onChange,
  filter,
  showAll,
}: {
  catalog: Catalog;
  onChange: (catalog: Catalog) => void;
  filter: CatalogFilter;
  showAll: () => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
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
    setExpanded((current) => new Set([...current, source.id]));
    onChange({ ...catalog, sources: [...catalog.sources, source] });
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Describe known brokers and their topics here. Credentials and network
        access are managed by the operator. New chargers start paused.
      </p>
      <Button variant="outline" onClick={addBroker}>
        Add broker
      </Button>
      {visible.length === 0 && catalog.sources.length > 0 && (
        <p className="text-sm text-muted-foreground">
          No matching hosts or chargers. Clear the search or change the evidence
          filter.
        </p>
      )}
      {visible.map(({ source, chargers }) => (
        <details
          key={source.id}
          className="rounded-xl border p-4"
          open={expanded.has(source.id)}
          onToggle={(event) => {
            const open = event.currentTarget.open;
            setExpanded((current) => {
              if (current.has(source.id) === open) return current;
              const next = new Set(current);
              if (open) next.add(source.id);
              else next.delete(source.id);
              return next;
            });
          }}
        >
          <summary className="cursor-pointer font-medium">
            {source.label}{" "}
            <span className="text-xs text-muted-foreground">
              {source.host} ·{" "}
              {source.verified
                ? "Observed broker"
                : "Candidate host · broker not yet observed"}
            </span>
          </summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
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
          </div>
          {chargers.map((charger) => {
            const editCharger = (next: CatalogCharger) =>
              editSource(source.id, {
                ...source,
                chargers: source.chargers.map((item) =>
                  item.id === charger.id ? next : item,
                ),
              });
            return (
              <div key={charger.id} className="mt-5 border-t pt-4">
                <div className="grid gap-3 sm:grid-cols-2">
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
                        {sensor.label}{" "}
                        <span className="text-muted-foreground">
                          · {sensor.key}
                        </span>
                      </summary>
                      <div className="mt-3 grid gap-3 sm:grid-cols-3">
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
                      </div>
                    </details>
                  );
                })}
              </div>
            );
          })}
          <div className="mt-4 flex gap-2">
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
          </div>
        </details>
      ))}
    </div>
  );
}
