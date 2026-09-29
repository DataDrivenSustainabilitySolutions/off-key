import type { CollectionPolicy } from "@/types/collection";
import { cn } from "@/lib/utils";
import { fieldClass } from "./InlineField";

export function PolicyPicker({
  value,
  onChange,
  label,
  disabled = false,
}: {
  value: CollectionPolicy;
  onChange: (value: CollectionPolicy) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <select
        aria-label={label}
        className={cn(fieldClass, "w-36 max-w-full")}
        disabled={disabled}
        value={value.mode}
        onChange={(e) =>
          onChange({
            mode: e.target.value as CollectionPolicy["mode"],
            interval_seconds:
              e.target.value === "sample" ? value.interval_seconds : 10,
          })
        }
      >
        <option value="off">Off</option>
        <option value="sample">Sampled</option>
        <option value="original">Original rate</option>
      </select>
      {value.mode === "sample" && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            aria-label={`${label} interval in seconds`}
            className={cn(fieldClass, "w-20")}
            type="number"
            required
            min={1}
            max={3600}
            step={1}
            disabled={disabled}
            value={value.interval_seconds || ""}
            onChange={(e) =>
              onChange({ ...value, interval_seconds: Number(e.target.value) })
            }
          />
          s
        </label>
      )}
    </div>
  );
}
