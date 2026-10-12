import { HelpTooltip } from "@/components/HelpTooltip";
import { cn } from "@/lib/utils";
import { CheckCircle2 } from "lucide-react";
import type { ElementType, ReactNode } from "react";

import type { FieldErrors } from "./config";
import { ERROR_CLASS, errorId } from "./formStyles";

export function FieldError({
  field,
  errors,
}: {
  field: string;
  errors: FieldErrors;
}) {
  return errors[field] ? (
    <p id={errorId(field)} className={ERROR_CLASS}>
      {errors[field]}
    </p>
  ) : null;
}

export function LaneCard({ title, description, selected = false, icon: Icon, onSelect }: {
  title: string;
  description?: string;
  selected?: boolean;
  icon: ElementType;
  onSelect?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "rounded-md border px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        selected ? "border-primary/40 bg-accent" : "border-border bg-card hover:bg-accent/60",
      )}
      aria-pressed={selected}
    >
      <span className="flex items-center gap-2 font-medium">
        <Icon className="size-4 text-primary" aria-hidden="true" />
        {title}
        {selected && <CheckCircle2 className="ml-auto size-4 text-primary" aria-hidden="true" />}
      </span>
      {description && <span className="mt-1 block text-sm text-muted-foreground">{description}</span>}
    </button>
  );
}

export function ConfigSection({
  title,
  description,
  help,
  icon: Icon,
  children,
}: {
  title: string;
  description?: string;
  help?: string;
  icon: ElementType;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 space-y-4 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-medium">{title}</h3>
            {help && <HelpTooltip label={title}>{help}</HelpTooltip>}
          </div>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      <div>{children}</div>
    </section>
  );
}
