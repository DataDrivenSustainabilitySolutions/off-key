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

export function LifecycleStep({
  number,
  title,
  description,
  icon: Icon,
}: {
  number: number;
  title: string;
  description: string;
  icon: ElementType;
}) {
  return (
    <div className="relative rounded-2xl border border-border/65 bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
            Phase {String(number).padStart(2, "0")}
          </div>
          <h3 className="mt-2 font-semibold tracking-[-0.01em]">{title}</h3>
        </div>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/[0.08] text-primary">
          <Icon className="size-4" />
        </span>
      </div>
      <p className="mt-4 text-sm leading-6 text-muted-foreground">
        {description}
      </p>
      <div className="mt-5 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary/70"
          style={{ width: `${number * 33.333}%` }}
        />
      </div>
    </div>
  );
}

export function ConfigSection({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description: string;
  icon: ElementType;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-border/65 bg-muted/[0.16] p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/[0.07] text-primary">
          <Icon className="size-4" />
        </span>
        <div>
          <h3 className="font-semibold tracking-[-0.01em]">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}
