import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  collectionMeasurements,
  configureCollection,
} from "@/lib/collection-selection";
import { policyLabel } from "@/lib/catalog-changes";
import type { Catalog, CollectionPolicy } from "@/types/collection";
import { fieldClass } from "./CatalogEditor";
import { PolicyPicker } from "./PolicyPicker";

const initialRate: CollectionPolicy = { mode: "sample", interval_seconds: 10 };

export function CollectionEditor({
  catalog,
  chargerIds,
  disabled,
  conflict,
  readOnly,
  onSave,
  onClose,
}: {
  catalog: Catalog;
  chargerIds: ReadonlySet<string>;
  disabled: boolean;
  conflict: boolean;
  readOnly: boolean;
  onSave: (catalog: Catalog) => void;
  onClose: () => void;
}) {
  const trigger = useRef(
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  const measurements = collectionMeasurements(catalog, chargerIds);
  const [policies, setPolicies] = useState(
    () =>
      new Map(
        measurements.map((item) => [
          item.id,
          item.policy.mode === "off" ? initialRate : item.policy,
        ]),
      ),
  );
  const [chosen, setChosen] = useState(
    () =>
      new Set(
        measurements
          .filter((item) => item.policy.mode !== "off")
          .map((item) => item.id),
      ),
  );
  const [rate, setRate] = useState<CollectionPolicy | null>(() => {
    const enabled = measurements.filter((item) => item.policy.mode !== "off");
    const first = enabled[0]?.policy ?? initialRate;
    return enabled.every(
      (item) =>
        item.policy.mode === first.mode &&
        item.policy.interval_seconds === first.interval_seconds,
    )
      ? first
      : null;
  });
  const categories = [
    ...new Set(measurements.map((item) => item.sensor.category)),
  ].sort();
  const selected = measurements.filter((item) => chosen.has(item.id));
  const valid = selected.every((item) => {
    const policy = policies.get(item.id)!;
    return (
      policy.mode !== "sample" ||
      (Number.isInteger(policy.interval_seconds) &&
        policy.interval_seconds >= 1 &&
        policy.interval_seconds <= 3600)
    );
  });
  const setSelection = (ids: string[], enabled: boolean) => {
    if (enabled && rate)
      setPolicies((current) => {
        const next = new Map(current);
        for (const id of ids) if (!chosen.has(id)) next.set(id, rate);
        return next;
      });
    setChosen((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (enabled) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };
  const changeRate = (next: CollectionPolicy | null) => {
    setRate(next);
    if (next)
      setPolicies(
        (current) =>
          new Map(
            measurements.map((item) => [
              item.id,
              chosen.has(item.id) ? next : current.get(item.id)!,
            ]),
          ),
      );
  };
  const names = catalog.sources
    .flatMap((source) => source.chargers)
    .filter((charger) => chargerIds.has(charger.id))
    .map((charger) => charger.label);

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        className="w-full gap-0 sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus();
        }}
      >
        <SheetHeader className="border-b p-6 pr-12">
          <SheetTitle className="text-xl">
            {readOnly ? "Collection details" : "Configure collection"}
          </SheetTitle>
          <SheetDescription>
            {readOnly ? "Viewing measurements for" : "Choose measurements for"}{" "}
            {chargerIds.size} {chargerIds.size === 1 ? "charger" : "chargers"}.{" "}
            {readOnly
              ? "An administrator can change collection."
              : "Unchecked measurements will be paused. Other chargers stay unchanged."}
          </SheetDescription>
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Show selected chargers</summary>
            <ul className="mt-2 max-h-24 space-y-1 overflow-y-auto">
              {names.map((name, index) => (
                <li key={index} className="break-words">
                  {name}
                </li>
              ))}
            </ul>
          </details>
        </SheetHeader>
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled && valid)
              onSave(
                configureCollection(
                  catalog,
                  chargerIds,
                  new Map(
                    selected.map((item) => [item.id, policies.get(item.id)!]),
                  ),
                ),
              );
          }}
        >
          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
            <fieldset disabled={disabled} className="space-y-2">
              <legend className="mb-3 text-base font-semibold">
                1. Choose measurements
              </legend>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm" aria-live="polite">
                  {selected.length} of {measurements.length} measurements
                  selected
                </p>
                <div className="flex flex-wrap gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setSelection(
                        measurements.map((item) => item.id),
                        true,
                      )
                    }
                  >
                    Select all measurements
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setSelection(
                        measurements.map((item) => item.id),
                        false,
                      )
                    }
                  >
                    Clear measurements
                  </Button>
                </div>
              </div>
              {categories.map((category) => {
                const items = measurements.filter(
                  (item) => item.sensor.category === category,
                );
                const count = items.filter((item) =>
                  chosen.has(item.id),
                ).length;
                return (
                  <div key={category} className="rounded-xl border">
                    <label className="flex cursor-pointer items-center gap-3 p-3">
                      <input
                        type="checkbox"
                        className="size-4"
                        checked={count === items.length}
                        ref={(input) => {
                          if (input)
                            input.indeterminate =
                              count > 0 && count < items.length;
                        }}
                        aria-label={`${category} measurements`}
                        onChange={(event) =>
                          setSelection(
                            items.map((item) => item.id),
                            event.target.checked,
                          )
                        }
                      />
                      <span className="flex-1 font-medium">{category}</span>
                      <span className="text-xs text-muted-foreground">
                        {count} / {items.length}
                      </span>
                    </label>
                    <details className="border-t px-3 py-2">
                      <summary className="cursor-pointer text-sm text-muted-foreground">
                        Choose individual {category.toLowerCase()} measurements
                      </summary>
                      <div className="mt-3 divide-y">
                        {items.map((item) => (
                          <label
                            key={item.id}
                            className="flex items-start gap-3 py-3 text-sm"
                          >
                            <input
                              type="checkbox"
                              className="mt-1 size-4"
                              checked={chosen.has(item.id)}
                              aria-label={`${item.charger} · ${item.sensor.label}`}
                              onChange={(event) =>
                                setSelection([item.id], event.target.checked)
                              }
                            />
                            <span className="min-w-0">
                              <span className="block font-medium">
                                {item.sensor.label}
                                {item.sensor.unit
                                  ? ` (${item.sensor.unit})`
                                  : ""}
                              </span>
                              <span className="block break-words text-xs text-muted-foreground">
                                {item.charger} ·{" "}
                                {item.sensor.value_type === "number"
                                  ? "Chart history"
                                  : "Latest value only"}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </details>
                  </div>
                );
              })}
              {measurements.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  These chargers have no measurements. Add sensor definitions in
                  Catalog first.
                </p>
              )}
            </fieldset>
            <fieldset
              disabled={disabled || selected.length === 0}
              className="space-y-3 border-t pt-5"
            >
              <legend className="mb-3 text-base font-semibold">
                2. Choose how often to keep data
              </legend>
              <label className="block text-sm">
                Collection frequency
                <select
                  className={`${fieldClass} mt-1`}
                  value={rate?.mode ?? "keep"}
                  onChange={(event) =>
                    changeRate(
                      event.target.value === "keep"
                        ? null
                        : {
                            mode: event.target.value as "sample" | "original",
                            interval_seconds:
                              event.target.value === "original"
                                ? 10
                                : (rate?.interval_seconds ?? 10),
                          },
                    )
                  }
                >
                  <option value="keep">Keep individual rates</option>
                  <option value="sample">
                    Keep the latest reading at an interval
                  </option>
                  <option value="original">Keep every incoming reading</option>
                </select>
              </label>
              {rate?.mode === "sample" && (
                <label className="flex items-center gap-3 text-sm">
                  Every
                  <input
                    className={`${fieldClass} max-w-28`}
                    aria-label="Collection interval in seconds"
                    type="number"
                    required
                    min={1}
                    max={3600}
                    step={1}
                    value={rate.interval_seconds || ""}
                    onChange={(event) =>
                      changeRate({
                        ...rate,
                        interval_seconds: Number(event.target.value),
                      })
                    }
                  />
                  seconds
                </label>
              )}
              <p className="text-xs leading-5 text-muted-foreground">
                {rate === null
                  ? "Individual rates are shown below. Newly selected measurements use their existing rate or a 10-second interval."
                  : rate.mode === "original"
                    ? "Records arrive at the source’s full rate. Storage use depends on how often it publishes."
                    : "Keep the newest reading in each interval. Quiet sensors do not produce repeated readings."}
              </p>
              <details>
                <summary className="cursor-pointer text-sm">
                  Customize individual rates
                </summary>
                <div className="mt-3 divide-y">
                  {selected.map((item) => (
                    <div key={item.id} className="space-y-2 py-3">
                      <p className="break-words text-sm">
                        {item.charger} · {item.sensor.label}
                      </p>
                      <PolicyPicker
                        label={`Rate for ${item.charger} ${item.sensor.label}`}
                        value={policies.get(item.id)!}
                        onChange={(policy) => {
                          setRate(null);
                          if (policy.mode === "off")
                            setSelection([item.id], false);
                          else
                            setPolicies((current) =>
                              new Map(current).set(item.id, policy),
                            );
                        }}
                      />
                    </div>
                  ))}
                </div>
              </details>
            </fieldset>
          </div>
          <div className="space-y-3 border-t bg-background p-6">
            {conflict && (
              <p role="alert" className="text-sm text-destructive">
                Someone saved a newer catalog. Close this editor and reload the
                saved catalog before continuing.
              </p>
            )}
            <p className="text-sm" role="status">
              {selected.length === 0
                ? "All measurements on these chargers will be paused."
                : `${selected.length} ${selected.length === 1 ? "measurement" : "measurements"} chosen · ${rate ? policyLabel(rate) : "Individual rates"}`}
            </p>
            {!valid && (
              <p role="alert" className="text-sm text-destructive">
                Sampling intervals must be whole seconds from 1 to 3600.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {readOnly
                ? "View only · these are the saved collection settings."
                : "This updates your draft. Collection changes only after Review changes → Apply collection."}
            </p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose}>
                {readOnly ? "Done" : "Cancel"}
              </Button>
              {!readOnly && (
                <Button type="submit" disabled={disabled || !valid}>
                  Update draft
                </Button>
              )}
            </div>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
