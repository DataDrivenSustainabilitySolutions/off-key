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
        "app-page-shell",
        className
      )}
    >
      <div className="app-page-content">
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
        "app-page-heading",
        className
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-1.5 text-xs text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="app-page-title">
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
        <div className="flex flex-col gap-3 border-b border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            {title ? (
              <div className="flex items-center gap-1">
                <h2 className="text-sm font-medium leading-6">{title}</h2>
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
  success: "bg-primary",
  warning: "bg-amber-500",
  danger: "bg-destructive",
  info: "bg-muted-foreground/45",
};

export function MetricCard({
  label,
  value,
  helper,
  help,
  tone = "default",
}: MetricCardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 sm:p-5">
      <div className="flex min-h-5 items-center gap-2 text-xs text-muted-foreground">
        <span className={cn("size-1.5 rounded-full", metricToneClassName[tone])} />
        {label}
        {help && <HelpTooltip label={label}>{help}</HelpTooltip>}
      </div>
      <div className="mt-2.5 text-2xl font-medium leading-none tracking-[-0.03em] tabular-nums">{value}</div>
      {helper ? <div className="mt-2 text-xs leading-5 text-muted-foreground">{helper}</div> : null}
    </div>
  );
}
