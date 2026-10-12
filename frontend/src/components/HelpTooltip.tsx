import { useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function HelpTooltip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <Tooltip open={open} onOpenChange={setOpen}>
      <TooltipTrigger asChild onClick={(event) => {
        event.preventDefault();
        setOpen(true);
      }}>
        <button
          type="button"
          aria-label={`About ${label}`}
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/25 sm:size-7"
        >
          <CircleHelp className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="max-h-[calc(100dvh-2rem)] max-w-[min(20rem,calc(100vw-2rem))] overflow-y-auto text-left leading-5 text-pretty">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}
