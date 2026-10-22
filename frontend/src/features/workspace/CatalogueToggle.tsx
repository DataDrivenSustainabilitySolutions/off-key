import type { Ref } from "react";
import { ChevronLeft } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Props = {
  open: boolean;
  onClick: () => void;
  ref?: Ref<HTMLButtonElement>;
  className?: string;
  hidden?: boolean;
};

export function CatalogueToggle({ open, onClick, ref, className, hidden }: Props) {
  const label = open ? "Hide catalogue" : "Show catalogue";
  return <Tooltip>
    <TooltipTrigger asChild>
      <button ref={ref} type="button" className={cn("catalogue-edge-toggle", className)} hidden={hidden}
        aria-label={label} aria-expanded={open} aria-controls="system-explorer" onClick={onClick}>
        <span className="catalogue-edge-face"><ChevronLeft size={14} aria-hidden="true" /></span>
      </button>
    </TooltipTrigger>
    <TooltipContent side="right" sideOffset={8} className="catalogue-toggle-tooltip z-[90]">{label}</TooltipContent>
  </Tooltip>;
}
