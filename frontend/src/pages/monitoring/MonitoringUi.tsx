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
  description: string;
  selected?: boolean;
  icon: ElementType;
  onSelect?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        selected ? "border-primary/35 bg-primary/[0.035]" : "border-border/70 bg-card hover:border-primary/35",
      )}
      aria-pressed={selected}
    >
      <span className="flex items-center gap-2 font-semibold">
        <Icon className="size-4 text-primary" aria-hidden="true" />
        {title}
        {selected && <CheckCircle2 className="ml-auto size-4 text-primary" aria-hidden="true" />}
      </span>
      <span className="mt-2 block text-sm text-muted-foreground">{description}</span>
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
    <section className="rounded-2xl border border-border/65 bg-muted/[0.16] p-4">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/[0.07] text-primary">
          <Icon className="size-4" />
        </span>
        <div>
          <div className="flex items-center gap-1">
            <h3 className="font-semibold tracking-[-0.01em]">{title}</h3>
            {help && <HelpTooltip label={title}>{help}</HelpTooltip>}
          </div>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}
