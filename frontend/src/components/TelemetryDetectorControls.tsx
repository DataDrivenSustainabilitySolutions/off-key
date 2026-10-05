import type { ChartDetector } from "@/lib/telemetry-chart";

interface Props {
  detectors: ChartDetector[];
  selected: { static?: string; adaptive?: string };
  unavailableIds?: ReadonlySet<string>;
  onSelect: (pane: "static" | "adaptive", id: string) => void;
}

export function TelemetryDetectorControls({ detectors, selected, unavailableIds, onSelect }: Props) {
  return (
    <div className="flex min-w-0 flex-wrap gap-3">
      {(["static", "adaptive"] as const).map((pane) => {
        const options = detectors.filter((detector) => detector.pane === pane);
        if (options.length < 2) return null;
        return (
          <label key={pane} className="flex min-w-0 max-w-full flex-col gap-1 text-xs">
            <span className="font-medium text-foreground">
              {pane === "static" ? "Static detector" : "Adaptive detector"}
            </span>
            <select
              value={selected[pane]}
              onChange={(event) => onSelect(pane, event.target.value)}
              className="h-9 w-full min-w-0 max-w-full rounded-md border border-input bg-background px-2 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {options.map((detector) => (
                <option key={detector.id} value={detector.id} disabled={unavailableIds?.has(detector.id)}>
                  {detector.name}{options.some((other) => other.id !== detector.id && other.name === detector.name) ? ` · ${detector.serviceId}` : ""}
                  {unavailableIds?.has(detector.id) ? " (unavailable)" : ""}
                </option>
              ))}
            </select>
          </label>
        );
      })}
    </div>
  );
}
