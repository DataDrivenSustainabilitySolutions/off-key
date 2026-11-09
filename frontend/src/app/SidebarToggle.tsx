import type { Ref } from "react";
import { PanelLeft, PanelLeftClose } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export const SIDEBAR_ID = "app-sidebar";

/** Shows or hides the sidebar; the same control opens and closes the mobile drawer. */
export function SidebarToggle({ open, onClick, ref }: { open: boolean; onClick: () => void; ref?: Ref<HTMLButtonElement> }) {
  const label = open ? "Hide sidebar" : "Show sidebar";
  return <Tooltip>
    <TooltipTrigger asChild>
      <button ref={ref} type="button" className="app-sidebar-toggle" aria-label={label} aria-expanded={open}
        aria-controls={open ? SIDEBAR_ID : undefined} onClick={onClick}>
        {open ? <PanelLeftClose size={16} strokeWidth={1.6} aria-hidden="true" /> : <PanelLeft size={16} strokeWidth={1.6} aria-hidden="true" />}
      </button>
    </TooltipTrigger>
    <TooltipContent side="right" sideOffset={6} className="app-sidebar-tooltip z-[90]">{label}</TooltipContent>
  </Tooltip>;
}
