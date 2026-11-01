import type { ReactNode } from "react";
import { HelpTooltip } from "@/components/HelpTooltip";
import { cn } from "@/lib/utils";

type GroupProps = {
  title?: string;
  help?: ReactNode;
  actions?: ReactNode;
  /** Small print under the group. */
  footer?: ReactNode;
  /** Pads free-form content; rows bring their own spacing. */
  padded?: boolean;
  children: ReactNode;
  className?: string;
};

/** A titled, rounded group of settings rows, as used inside the settings overlay. */
export function SettingsGroup({ title, help, actions, footer, padded, children, className }: GroupProps) {
  return (
    <section className={cn("app-settings-group", className)} aria-label={title}>
      {(title || actions) && (
        <header className="app-settings-group-header">
          {title && <h3>{title}{help && <HelpTooltip label={title}>{help}</HelpTooltip>}</h3>}
          {actions && <div className="app-settings-group-actions">{actions}</div>}
        </header>
      )}
      <div className={cn("app-settings-group-body", padded && "is-padded")}>{children}</div>
      {footer && <div className="app-settings-group-footer">{footer}</div>}
    </section>
  );
}

type RowProps = {
  label: ReactNode;
  detail?: ReactNode;
  /** A value, control or actions shown on the trailing side. */
  children?: ReactNode;
  leading?: ReactNode;
  tone?: "default" | "warning" | "danger";
  className?: string;
};

export function SettingsRow({ label, detail, children, leading, tone = "default", className }: RowProps) {
  return (
    <div className={cn("app-settings-row", className)} data-tone={tone === "default" ? undefined : tone}>
      {leading}
      <div className="app-settings-row-copy">
        <div className="app-settings-row-label">{label}</div>
        {detail && <div className="app-settings-row-detail">{detail}</div>}
      </div>
      {children !== undefined && <div className="app-settings-row-trailing">{children}</div>}
    </div>
  );
}
