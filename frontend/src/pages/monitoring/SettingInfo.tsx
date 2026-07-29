import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Info } from "lucide-react";
import type { ReactNode } from "react";

import { LABEL_CLASS } from "./formStyles";

export function SettingInfo({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`About ${label}`}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none transition-colors hover:bg-primary/10 hover:text-primary focus-visible:bg-primary/10 focus-visible:text-primary focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          <Info className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        sideOffset={6}
        className="max-w-80 text-left leading-5 text-pretty"
      >
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

export function SettingLabel({
  label,
  help,
  htmlFor,
  className,
}: {
  label: string;
  help: ReactNode;
  htmlFor: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1", className)}>
      <label className={LABEL_CLASS} htmlFor={htmlFor}>
        {label}
      </label>
      <SettingInfo label={label}>{help}</SettingInfo>
    </div>
  );
}
