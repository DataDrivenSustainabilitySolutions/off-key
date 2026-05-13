import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type PageShellProps = {
  children: ReactNode;
  className?: string;
};

export function PageShell({ children, className }: PageShellProps) {
  return (
    <main
      className={cn(
        "min-h-[calc(100vh-3.5rem)] bg-background text-foreground",
        className
      )}
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        {children}
      </div>
    </main>
  );
}

type PageHeaderProps = {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="overflow-visible pb-1 text-2xl font-semibold leading-tight tracking-normal sm:text-3xl">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

type SectionPanelProps = {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
};

export function SectionPanel({
  title,
  description,
  actions,
  children,
  className,
  contentClassName,
}: SectionPanelProps) {
  return (
    <Card className={cn("gap-0 overflow-hidden border-border/80 shadow-xs", className)}>
      {(title || description || actions) && (
        <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            {title ? (
              <div className="text-base font-semibold leading-6">{title}</div>
            ) : null}
            {description ? (
              <div className="mt-1 text-sm text-muted-foreground">{description}</div>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
        </div>
      )}
      <CardContent className={cn("p-5", contentClassName)}>{children}</CardContent>
    </Card>
  );
}

type MetricCardProps = {
  label: string;
  value: ReactNode;
  helper?: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "info";
};

const metricToneClassName: Record<NonNullable<MetricCardProps["tone"]>, string> = {
  default: "border-border/80 bg-card",
  success: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-100",
  warning: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100",
  danger: "border-red-200 bg-red-50 text-red-950 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-100",
  info: "border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-900/60 dark:bg-sky-950/20 dark:text-sky-100",
};

export function MetricCard({
  label,
  value,
  helper,
  tone = "default",
}: MetricCardProps) {
  return (
    <div className={cn("rounded-lg border p-4", metricToneClassName[tone])}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold leading-none">{value}</div>
      {helper ? <div className="mt-2 text-xs text-muted-foreground">{helper}</div> : null}
    </div>
  );
}
