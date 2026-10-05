import { useState } from "react";
import {
  getDefaultDetectorId,
  type ChartDetector,
  type SelectedDetectorIds,
} from "@/lib/telemetry-chart";

type DetectorSelection = Partial<Record<"static" | "adaptive", ChartDetector>>;

/** Remember the chosen detector independently of the rolling observation catalog. */
export const useDetectorSelection = (catalog: readonly ChartDetector[], context: string) => {
  const [state, setState] = useState<{ context: string; selected: DetectorSelection }>({
    context, selected: {},
  });
  const remembered = state.context === context ? state.selected : {};
  const defaultFor = (pane: "static" | "adaptive") =>
    catalog.find((detector) => detector.id === getDefaultDetectorId(catalog, pane));
  const selectedFor = (pane: "static" | "adaptive") => remembered[pane]
    ? catalog.find((detector) => detector.id === remembered[pane]?.id) ?? remembered[pane]
    : defaultFor(pane);
  const selected: DetectorSelection = {
    static: selectedFor("static"),
    adaptive: selectedFor("adaptive"),
  };
  // A guarded state adjustment persists first defaults and resets only when chart context changes.
  if (state.context !== context || selected.static !== remembered.static || selected.adaptive !== remembered.adaptive) {
    setState({ context, selected });
  }
  const selectedDetectorIds: SelectedDetectorIds = {
    static: selected.static?.id,
    adaptive: selected.adaptive?.id,
  };
  const availableIds = new Set(catalog.map(({ id }) => id));
  const unavailable = Object.values(selected).filter((detector): detector is ChartDetector =>
    detector !== undefined && !availableIds.has(detector.id));
  const controlCatalog = [...catalog, ...unavailable];
  const unavailableIds = new Set(unavailable.map(({ id }) => id));
  const onSelect = (pane: "static" | "adaptive", id: string) => {
    const detector = controlCatalog.find((candidate) => candidate.pane === pane && candidate.id === id);
    if (detector) setState({ context, selected: { ...selected, [pane]: detector } });
  };
  return { selectedDetectorIds, controlCatalog, unavailableIds, onSelect };
};
