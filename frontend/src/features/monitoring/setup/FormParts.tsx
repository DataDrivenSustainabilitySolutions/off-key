import { HelpTooltip } from "@/components/HelpTooltip";
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
