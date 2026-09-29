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
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none transition-colors hover:bg-primary/10 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring/40"
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
