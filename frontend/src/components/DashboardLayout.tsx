import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { HelpTooltip } from "@/components/HelpTooltip";
import { cn } from "@/lib/utils";

type PageShellProps = {
  children: ReactNode;
  className?: string;
};

export function PageShell({ children, className }: PageShellProps) {
  return (
    <main
      className={cn(
        "app-canvas min-h-[calc(100vh-4rem)] text-foreground",
        className
      )}
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 sm:px-6 sm:py-7 lg:px-8 lg:py-8">
        {children}
      </div>
    </main>
  );
}

type PageHeaderProps = {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({
  title,
  eyebrow,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <span className="size-1.5 rounded-full bg-primary" aria-hidden="true" />
            {eyebrow}
          </p>
        ) : null}
        <h1 className="overflow-visible pb-1 text-3xl font-semibold leading-[1.08] tracking-[-0.03em] sm:text-4xl">
          {title}
        </h1>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

type SectionPanelProps = {
  title?: ReactNode;
  description?: ReactNode;
  help?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
};

export function SectionPanel({
  title,
  description,
  help,
  actions,
  children,
  className,
  contentClassName,
}: SectionPanelProps) {
  return (
    <Card className={cn("gap-0 overflow-hidden py-0", className)}>
      {(title || description || actions) && (
        <div className="flex flex-col gap-3 border-b border-border/60 px-5 py-4.5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            {title ? (
              <div className="flex items-center gap-1">
                <h2 className="text-base font-semibold leading-6 tracking-[-0.01em]">{title}</h2>
                {help && <HelpTooltip label={typeof title === "string" ? title : "this section"}>{help}</HelpTooltip>}
              </div>
            ) : null}
            {description ? (
              <div className="mt-1 text-sm text-muted-foreground">{description}</div>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
        </div>
      )}
      <CardContent className={cn("p-5 sm:p-6", contentClassName)}>{children}</CardContent>
    </Card>
  );
}

type MetricCardProps = {
  label: string;
  value: ReactNode;
  helper?: ReactNode;
  help?: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "info";
};

const metricToneClassName: Record<NonNullable<MetricCardProps["tone"]>, string> = {
  default: "bg-muted-foreground/45",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-red-500",
  info: "bg-sky-500",
};

export function MetricCard({
  label,
  value,
  helper,
  help,
  tone = "default",
}: MetricCardProps) {
  return (
    <div className="rounded-2xl border border-border/65 bg-card p-4 shadow-[0_1px_2px_hsl(220_20%_10%/0.025)] sm:p-5">
      <div className="flex min-h-6 items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <span className={cn("size-1.5 rounded-full", metricToneClassName[tone])} />
        {label}
        {help && <HelpTooltip label={label}>{help}</HelpTooltip>}
      </div>
      <div className="mt-3 text-3xl font-semibold leading-none tracking-[-0.04em] tabular-nums">{value}</div>
      {helper ? <div className="mt-2 text-xs leading-5 text-muted-foreground">{helper}</div> : null}
    </div>
  );
}
