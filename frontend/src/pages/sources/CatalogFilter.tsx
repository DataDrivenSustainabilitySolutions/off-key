import type { CatalogFilter as Filter } from "@/lib/catalog-view";
import { HelpTooltip } from "@/components/HelpTooltip";
import { fieldClass } from "./InlineField";

export function CatalogFilter({
  value,
  onChange,
  categories,
}: {
  value: Filter;
  onChange: (filter: Filter) => void;
  categories: string[];
}) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
        <label className="col-span-2 min-w-0 text-sm sm:col-span-1">
          <span className="block min-h-6">Search catalog</span>
          <input
            type="search"
            className={fieldClass}
            value={value.query}
            placeholder="Broker, charger, sensor or topic…"
            onChange={(e) => onChange({ ...value, query: e.target.value })}
          />
        </label>
        <div className="min-w-0 text-sm">
          <div className="flex items-center gap-1">
            <label htmlFor="broker-evidence">Broker evidence</label>
            <HelpTooltip label="Broker evidence">
              Observed brokers were seen during inventory discovery.
            </HelpTooltip>
          </div>
          <select
            id="broker-evidence"
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
        </div>
        <label className="min-w-0 text-sm">
          <span className="block min-h-6">Category</span>
          <select
            className={fieldClass}
            value={value.category}
            onChange={(event) =>
              onChange({ ...value, category: event.target.value })
            }
          >
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category}>{category}</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
