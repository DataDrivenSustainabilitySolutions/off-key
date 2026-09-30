import { useRef, useState } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HelpTooltip } from "@/components/HelpTooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { visibleMeasurements, type CatalogFilter } from "@/lib/catalog-view";
import { policyLabel } from "@/lib/catalog-changes";
import { validPolicy } from "@/lib/collection-selection";
import {
  effectivePolicy,
  pausedPolicy,
  type Catalog,
  type CatalogSource,
  type CatalogCharger,
  type CatalogSensor,
  type CatalogSnapshot,
} from "@/types/collection";
import { InlineField, fieldClass } from "./InlineField";
import { PolicyPicker } from "./PolicyPicker";
import { MeasurementDetails } from "./MeasurementDetails";
import { SensorActivityBadge } from "./SensorActivityBadge";

export function ChargerEditor({
  catalog,
  source,
  charger,
  saved,
  snapshot,
  activityAvailable,
  now,
  disabled,
  filter,
  showAll,
  selected,
  onSelect,
  onChange,
  onRemove,
}: {
  catalog: Catalog;
  source: CatalogSource;
  charger: CatalogCharger;
  saved?: CatalogCharger;
  snapshot: CatalogSnapshot;
  activityAvailable: boolean;
  now: number;
  disabled: boolean;
  filter: CatalogFilter;
  showAll: () => void;
  selected: ReadonlySet<string>;
  onSelect: (ids: string[], checked: boolean) => void;
  onChange: (charger: CatalogCharger) => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<number | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const sensors = visibleMeasurements(source, charger, filter);
  const ids = sensors.map((sensor) => `${charger.id}:${sensor.key}`);
  const selectedCount = ids.filter((id) => selected.has(id)).length;
  const policies = charger.sensors.map((sensor) =>
    effectivePolicy(catalog, charger, sensor),
  );
  const rates = new Set(policies.map(policyLabel));
  const savedSource = snapshot.catalog.sources.find(
    (item) => item.id === source.id,
  );
  const savedBinding =
    savedSource?.host === source.host && savedSource?.port === source.port &&
    saved?.local_id === charger.local_id;
  const metadata = (patch: Partial<CatalogCharger>) => {
    showAll();
    onChange({ ...charger, ...patch });
  };
  const editSensor = (index: number, patch: Partial<CatalogSensor>) =>
    onChange({
      ...charger,
      sensors: charger.sensors.map((item, i) =>
        i === index ? { ...item, ...patch } : item,
      ),
    });
  const addSensor = (button: HTMLElement) => {
    let number = 1;
    while (charger.sensors.some((sensor) => sensor.key === `sensor-${number}`))
      number += 1;
    const key = `sensor-${number}`;
    showAll();
    setOpen(true);
    trigger.current = button;
    setDetails(charger.sensors.length);
    onChange({
      ...charger,
      sensors: [
        ...charger.sensors,
        {
          key,
          label: "New measurement",
          category: "Other",
          value_type: "number",
          unit: null,
          upstream_topic: `device/evCharger/${charger.local_id}/${key}`,
          policy: pausedPolicy,
        },
      ],
    });
  };

  return (
    <section
      aria-label={`Charger ${charger.label}`}
      className="rounded-lg border bg-card"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-3">
        <input
          type="checkbox"
          className="size-4 shrink-0"
          aria-label={`Select measurements for ${charger.label}`}
          disabled={disabled || ids.length === 0}
          checked={ids.length > 0 && selectedCount === ids.length}
          ref={(input) => {
            if (input)
              input.indeterminate =
                selectedCount > 0 && selectedCount < ids.length;
          }}
          onChange={(event) => onSelect(ids, event.target.checked)}
        />
        <div className="min-w-0 flex-1 basis-40">
          <InlineField
            className="font-medium"
            label="Charger name"
            value={charger.label}
            maxLength={120}
            disabled={disabled}
            onChange={(label) => metadata({ label })}
          />
          <p className="ml-2 text-xs text-muted-foreground">
            {policies.filter((policy) => policy.mode !== "off").length}/
            {policies.length} enabled ·{" "}
            {rates.size > 1
              ? "Mixed rates"
              : ([...rates][0] ?? "No measurements")}
          </p>
        </div>
        <div className="min-w-0 max-w-full text-sm">
          <span className="ml-2 text-xs text-muted-foreground">Local ID</span>
          <InlineField
            label="Local charger ID"
            value={charger.local_id}
            maxLength={80}
            disabled={disabled}
            onChange={(local_id) =>
              metadata({
                local_id,
                sensors: charger.sensors.map((sensor) => ({
                  ...sensor,
                  upstream_topic: sensor.upstream_topic.replace(
                    `device/evCharger/${charger.local_id}/`,
                    `device/evCharger/${local_id}/`,
                  ),
                })),
              })
            }
          />
        </div>
        <Button
          variant="ghost"
          aria-label={`${open ? "Hide" : "Show"} measurements for ${charger.label}`}
          aria-expanded={open}
          aria-controls={`measurements-${charger.id}`}
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronDown /> : <ChevronRight />} Measurements (
          {sensors.length})
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for charger ${charger.label}`}
              disabled={disabled}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onRemove}>
              Remove charger
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {JSON.stringify(charger) !== JSON.stringify(saved) && (
          <span className="text-xs text-amber-700 dark:text-amber-300">
            Unsaved changes
          </span>
        )}
      </div>
      {open && (
        <div id={`measurements-${charger.id}`} className="border-t">
          <div className="hidden grid-cols-[1.5rem_minmax(0,1fr)_minmax(0,.7fr)_minmax(17rem,1fr)_4rem] gap-3 bg-muted/25 px-4 py-2 text-xs text-muted-foreground lg:grid">
            <span />
            <span>Measurement</span>
            <span>Category</span>
            <span className="flex items-center gap-1">
              Collection{" "}
              <HelpTooltip label="Collection modes">
                Off stops collection. Sampled keeps the latest reading in each
                interval. Original rate keeps every incoming reading.
                Non-numeric measurements keep their latest value only.
              </HelpTooltip>
            </span>
            <span />
          </div>
          <div className="divide-y">
            {sensors.map((sensor) => {
              const index = charger.sensors.indexOf(sensor);
              const id = `${charger.id}:${sensor.key}`;
              const policy = effectivePolicy(catalog, charger, sensor);
              const savedSensor = savedBinding
                ? saved?.sensors.find(
                    (item) => item.key === sensor.key &&
                      item.upstream_topic === sensor.upstream_topic &&
                      item.value_type === sensor.value_type,
                  )
                : undefined;
              return (
                <div
                  key={index}
                  role="group"
                  aria-label={`Measurement ${sensor.label}`}
                  className="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-3 py-3 sm:px-4 lg:grid-cols-[1.5rem_minmax(0,1fr)_minmax(0,.7fr)_minmax(17rem,1fr)_4rem]"
                >
                  <input
                    type="checkbox"
                    className="size-4"
                    aria-label={`Select ${charger.label} · ${sensor.label}`}
                    disabled={disabled}
                    checked={selected.has(id)}
                    onChange={(event) => onSelect([id], event.target.checked)}
                  />
                  <div className="flex min-w-0 flex-wrap items-baseline">
                    <InlineField
                      label={`Name for ${sensor.key}`}
                      value={sensor.label}
                      maxLength={120}
                      disabled={disabled}
                      onChange={(label) => {
                        showAll();
                        editSensor(index, { label });
                      }}
                    />
                    <InlineField
                      className="text-xs text-muted-foreground"
                      label={`Unit for ${sensor.label}`}
                      value={sensor.unit ?? ""}
                      maxLength={32}
                      placeholder="—"
                      optional
                      disabled={disabled}
                      onChange={(unit) =>
                        editSensor(index, { unit: unit || null })
                      }
                    />
                    <SensorActivityBadge
                      activity={
                        savedSensor
                          ? snapshot.sensor_activity?.[charger.id]?.[sensor.key]
                          : undefined
                      }
                      policy={
                        savedSensor && saved
                          ? effectivePolicy(snapshot.catalog, saved, savedSensor)
                          : undefined
                      }
                      available={activityAvailable}
                      now={now}
                    />
                  </div>
                  <div className="col-start-2 min-w-0 text-xs text-muted-foreground lg:col-start-auto">
                    <InlineField
                      label={`Category for ${sensor.label}`}
                      value={sensor.category}
                      maxLength={60}
                      disabled={disabled}
                      onChange={(category) => {
                        showAll();
                        editSensor(index, { category });
                      }}
                    />
                  </div>
                  <div className="col-span-3 col-start-1 min-w-0 sm:col-span-2 sm:col-start-2 lg:col-span-1 lg:col-start-auto">
                    <PolicyPicker
                      label={`Collection for ${charger.label} · ${sensor.label}`}
                      value={policy}
                      disabled={disabled}
                      onChange={(policy) => editSensor(index, { policy })}
                    />
                    {!validPolicy(policy) && (
                      <p role="alert" className="mt-1 text-xs text-destructive">
                        Use whole seconds from 1 to 3600.
                      </p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="col-start-3 row-start-1 lg:col-start-auto lg:row-start-auto"
                    aria-label={`Details for ${charger.label} · ${sensor.label}`}
                    onClick={(event) => {
                      trigger.current = event.currentTarget;
                      setDetails(index);
                    }}
                  >
                    Details
                  </Button>
                </div>
              );
            })}
          </div>
          {sensors.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">
              {charger.sensors.length
                ? "No measurements match the filters."
                : "No measurements yet."}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t p-3">
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={(event) => addSensor(event.currentTarget)}
            >
              Add measurement
            </Button>
            <div className="flex min-w-0 items-center gap-1">
              <select
                className={`${fieldClass} max-w-64`}
                aria-label={`Copy measurements to ${charger.label}`}
                disabled={disabled}
                value=""
                onChange={(event) => {
                  const template = catalog.sources
                    .flatMap((item) => item.chargers)
                    .find((item) => item.id === event.target.value);
                  if (template)
                    metadata({
                      policy: pausedPolicy,
                      sensors: template.sensors.map((sensor) => ({
                        ...sensor,
                        policy: null,
                        upstream_topic: sensor.upstream_topic.replace(
                          `device/evCharger/${template.local_id}/`,
                          `device/evCharger/${charger.local_id}/`,
                        ),
                      })),
                    });
                }}
              >
                <option value="">Copy measurements from…</option>
                {catalog.sources
                  .flatMap((item) => item.chargers)
                  .filter(
                    (item) => item.id !== charger.id && item.sensors.length > 0,
                  )
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
              </select>
              <HelpTooltip label="Copy measurements">
                Replaces this charger's measurements and turns their collection
                off. Save changes applies the replacement.
              </HelpTooltip>
            </div>
          </div>
        </div>
      )}
      {details !== null && charger.sensors[details] && (
        <MeasurementDetails
          sensor={charger.sensors[details]!}
          charger={charger}
          disabled={disabled}
          trigger={trigger}
          onChange={(patch) => {
            showAll();
            editSensor(details, patch);
          }}
          onClose={() => setDetails(null)}
          onRemove={() => {
            onChange({
              ...charger,
              sensors: charger.sensors.filter((_, index) => index !== details),
            });
            setDetails(null);
          }}
        />
      )}
    </section>
  );
}
