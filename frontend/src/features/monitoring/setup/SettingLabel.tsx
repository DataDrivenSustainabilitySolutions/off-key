import { HelpTooltip } from "@/components/HelpTooltip";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

import { LABEL_CLASS } from "./formStyles";

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
      {help && <HelpTooltip label={label}>{help}</HelpTooltip>}
    </div>
  );
}
