import type { RefObject } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import type { CatalogCharger, CatalogSensor } from "@/types/collection";
import { fieldClass } from "./InlineField";

export function MeasurementDetails({
  sensor,
  charger,
  disabled,
  onChange,
  onRemove,
  onClose,
  trigger,
}: {
  sensor: CatalogSensor;
  charger: CatalogCharger;
  disabled: boolean;
  onChange: (patch: Partial<CatalogSensor>) => void;
  onRemove: () => void;
  onClose: () => void;
  trigger: RefObject<HTMLElement | null>;
}) {
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        className="w-full sm:max-w-lg"
        onCloseAutoFocus={(event) => {
          if (trigger.current?.isConnected) {
            event.preventDefault();
            trigger.current.focus();
          }
        }}
      >
        <SheetHeader className="border-b pr-12">
          <SheetTitle>Measurement details</SheetTitle>
          <SheetDescription>
            {charger.label} · {sensor.label}
          </SheetDescription>
        </SheetHeader>
        <fieldset
          disabled={disabled}
          className="space-y-4 overflow-y-auto px-4 pb-4"
        >
          <label className="block text-sm">
            Sensor key
            <input
              className={fieldClass}
              value={sensor.key}
              maxLength={160}
              required
              onChange={(event) => onChange({ key: event.target.value })}
            />
          </label>
          <label className="block text-sm">
            Upstream topic
            <input
              className={fieldClass}
              value={sensor.upstream_topic}
              maxLength={512}
              required
              onChange={(event) =>
                onChange({ upstream_topic: event.target.value })
              }
            />
          </label>
          <label className="block text-sm">
            Value type
            <select
              className={fieldClass}
              value={sensor.value_type}
              onChange={(event) =>
                onChange({
                  value_type: event.target.value as CatalogSensor["value_type"],
                })
              }
            >
              <option value="number">Number</option>
              <option value="boolean">Boolean</option>
              <option value="text">Text</option>
              <option value="identifier">Identifier</option>
            </select>
          </label>
          <p className="text-xs text-muted-foreground">
            {sensor.value_type === "number"
              ? "Chart history"
              : "Latest value only"}{" "}
            · Edits are included in Save changes.
          </p>
          <Button variant="outline" onClick={onRemove}>
            Remove measurement
          </Button>
        </fieldset>
        <div className="mt-auto border-t p-4 text-xs text-muted-foreground break-all">
          Charger ID: {charger.id}
        </div>
      </SheetContent>
    </Sheet>
  );
}
