import type { CollectionPolicy } from "@/types/collection";
import { fieldClass } from "./CatalogEditor";

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
    <div className="flex flex-wrap gap-2">
      <select
        aria-label={label}
        className={`${fieldClass} max-w-48`}
        disabled={disabled}
        value={value.mode}
        onChange={(e) =>
          onChange({
            mode: e.target.value as CollectionPolicy["mode"],
            interval_seconds:
              e.target.value === "original" ? 10 : value.interval_seconds,
          })
        }
      >
        <option value="off">Off</option>
        <option value="sample">Latest every…</option>
        <option value="original">Original rate</option>
      </select>
      {value.mode === "sample" && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            aria-label={`${label} interval in seconds`}
            className={`${fieldClass} max-w-24`}
            type="number"
            required
            min={1}
            max={3600}
            disabled={disabled}
            value={value.interval_seconds || ""}
            onChange={(e) =>
              onChange({ ...value, interval_seconds: Number(e.target.value) })
            }
          />
          seconds
        </label>
      )}
    </div>
  );
}
