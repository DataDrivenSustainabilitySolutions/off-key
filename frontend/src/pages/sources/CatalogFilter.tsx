import type { CatalogFilter as Filter } from "@/lib/catalog-view";
import { fieldClass } from "./CatalogEditor";

export function CatalogFilter({
  value,
  onChange,
}: {
  value: Filter;
  onChange: (filter: Filter) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
        <label className="min-w-0 text-sm">
          Search catalog
          <input
            type="search"
            className={fieldClass}
            value={value.query}
            placeholder="Broker, charger, sensor or topic…"
            onChange={(e) => onChange({ ...value, query: e.target.value })}
          />
        </label>
        <label className="text-sm">
          Broker evidence
          <select
            className={fieldClass}
            value={value.evidence}
            onChange={(e) =>
              onChange({
                ...value,
                evidence: e.target.value as Filter["evidence"],
              })
            }
          >
            <option value="all">All hosts</option>
            <option value="observed">Observed brokers</option>
            <option value="candidate">Candidate hosts</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        Search by name, host or measurement. Observed brokers were seen during
        inventory discovery; their live connection is shown separately.
      </p>
    </div>
  );
}
