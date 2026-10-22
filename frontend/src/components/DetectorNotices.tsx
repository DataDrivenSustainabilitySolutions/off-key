import type { ChartDetector, SelectedDetectorIds } from "@/lib/telemetry-detectors";

type Props = {
  controlCatalog: readonly ChartDetector[];
  selectedDetectorIds: SelectedDetectorIds;
  unavailableIds: ReadonlySet<string>;
  secondarySeries: readonly { id: string }[];
  className?: string;
};

/** Explain a chosen detector that has nothing to plot in the current range. */
export function DetectorNotices({ controlCatalog, selectedDetectorIds, unavailableIds, secondarySeries, className }: Props) {
  return controlCatalog.filter((detector) => detector.id === selectedDetectorIds[detector.pane]
    && !secondarySeries.some((series) => series.id === detector.id)).map((detector) =>
    <p key={detector.id} className={className} role="status">{detector.name}: {unavailableIds.has(detector.id)
      ? "No evaluated observations available" : "No evaluated observations in selected range"}</p>);
}
