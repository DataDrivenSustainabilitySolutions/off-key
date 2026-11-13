import { Activity, Waves } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { HistoryPreference } from "@/types/telemetry-history";
import { intervalLabel } from "./history-presentation";

export function HistoryViewControls({ value, onChange, intervalMs }: {
  value: HistoryPreference; onChange: (value: HistoryPreference) => void; intervalMs?: number;
}) {
  const automatic = value.mode === "auto";
  const Icon = automatic ? Waves : Activity;
  return <Tooltip><TooltipTrigger asChild>
    <button type="button" className="ex-history-view" aria-label="Automatic averaging" aria-pressed={automatic}
      onClick={() => onChange({ mode: automatic ? "raw" : "auto" })}>
      <Icon size={15} aria-hidden="true" />
    </button>
  </TooltipTrigger><TooltipContent sideOffset={6}>
    <span className="block">{automatic ? "Show raw readings" : "Use automatic averaging"}</span>
    {automatic && !!intervalMs && <span className="block opacity-70">{intervalLabel(intervalMs)} mean · min–max</span>}
  </TooltipContent></Tooltip>;
}
