import { SectionPanel } from "@/components/DashboardLayout";
import { catalogChanges, policyLabel } from "@/lib/catalog-changes";
import { Button } from "@/components/ui/button";
import type { Catalog, CatalogPreview } from "@/types/collection";
import { effectivePolicy } from "@/types/collection";

export function CollectionReview({
  saved,
  preview,
  pauseMonitors,
  busy,
  conflict,
  onPauseMonitors,
  onApply,
}: {
  saved: Catalog;
  preview: CatalogPreview;
  pauseMonitors: boolean;
  busy: boolean;
  conflict: boolean;
  onPauseMonitors: (pause: boolean) => void;
  onApply: () => void;
}) {
  const changes = catalogChanges(saved, preview.catalog);
  const active = preview.catalog.sources.flatMap((source) =>
    source.chargers.flatMap((charger) => {
      const groups = new Map<string, number>();
      for (const sensor of charger.sensors) {
        const policy = effectivePolicy(preview.catalog, charger, sensor);
        if (policy.mode === "off") continue;
        const label = `${sensor.category} · ${policyLabel(policy)}`;
        groups.set(label, (groups.get(label) ?? 0) + 1);
      }
      return groups.size ? [{ source, charger, groups }] : [];
    }),
  );
  return (
    <SectionPanel
      title="Collection after applying"
      description="Nothing changes until you apply this revision."
    >
      <p className="mb-4 font-medium">
        {active.length} active chargers · {preview.selected_sensors}{" "}
        measurements
      </p>
      {active.length === 0 && (
        <p className="mb-4 text-sm">
          Collection will be paused for all chargers.
        </p>
      )}
      <div className="mb-5 space-y-3" aria-label="Collection plan">
        {active.map(({ source, charger, groups }) => (
          <div key={charger.id} className="rounded-xl border p-4">
            <p className="break-words font-medium">{charger.label}</p>
            <p className="mt-1 break-all text-xs text-muted-foreground">
              {source.host}
            </p>
            {!source.verified && (
              <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
                Candidate host: MQTT availability has not been verified.
              </p>
            )}
            <ul className="mt-3 space-y-1 text-sm">
              {[...groups].map(([label, count]) => (
                <li key={label}>
                  {label} · {count}{" "}
                  {count === 1 ? "measurement" : "measurements"}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <details className="mb-5 rounded-lg border p-4">
        <summary className="cursor-pointer text-sm font-medium">
          See all catalog changes
        </summary>
        <div
          className="mt-4 max-h-80 space-y-4 overflow-y-auto"
          aria-label="Catalog change summary"
        >
          {changes.length === 0 && (
            <p className="text-sm">No catalog changes.</p>
          )}
          {changes.map((group, index) => (
            <div key={index}>
              <p className="break-words text-sm font-medium">{group.title}</p>
              <ul className="mt-1 list-inside list-disc space-y-1 text-sm text-muted-foreground">
                {group.details.map((detail, i) => (
                  <li className="break-words" key={i}>
                    {detail}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </details>
      <p className="text-sm">
        {preview.selected_sensors} selected sensors. Sampled numeric history: up
        to {preview.sampled_rows_per_day_ceiling.toLocaleString()} rows per day
        when every stream reports continuously. {preview.original_rate_sensors}{" "}
        numeric sensors use original rate, with no fixed daily bound.
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Text, identifiers, and booleans keep only their latest state. Retained
        snapshots do not create fresh numeric history.
      </p>
      {preview.affected_monitors.length > 0 && (
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={pauseMonitors}
            onChange={(e) => onPauseMonitors(e.target.checked)}
          />
          Pause affected monitors:{" "}
          {preview.affected_monitors.map((monitor) => monitor.name).join(", ")}.
          Restart them with fresh calibration after this change.
        </label>
      )}
      <Button
        className="mt-4"
        disabled={
          busy ||
          conflict ||
          (preview.affected_monitors.length > 0 && !pauseMonitors)
        }
        onClick={onApply}
      >
        Apply collection
      </Button>
    </SectionPanel>
  );
}
