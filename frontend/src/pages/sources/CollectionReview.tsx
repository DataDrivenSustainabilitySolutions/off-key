import { SectionPanel } from "@/components/DashboardLayout";
import { catalogChanges } from "@/lib/catalog-changes";
import { Button } from "@/components/ui/button";
import type { Catalog, CatalogPreview } from "@/types/collection";

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
  return (
    <SectionPanel
      title="Review collection changes"
      description="Nothing changes until you apply this revision."
    >
      <div
        className="mb-5 max-h-80 space-y-4 overflow-y-auto rounded-lg border p-4"
        aria-label="Catalog change summary"
      >
        {changes.length === 0 && <p className="text-sm">No catalog changes.</p>}
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
