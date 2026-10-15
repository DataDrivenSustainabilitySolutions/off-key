import type { MouseEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { isActiveApplicationPath, workspaceNavItems } from "./application-navigation";

type Props = {
  monitoringHref?: string;
  hrefs?: Record<string, string>;
  onMonitoringClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
};

export function WorkspaceNavigation({ monitoringHref = "/", hrefs, onMonitoringClick, onNavigate }: Props) {
  const { pathname } = useLocation();
  return <div className="app-workspace-links" role="group" aria-label="Workspaces">
    {workspaceNavItems.map(item => <Link key={item.href} className="app-workspace-link"
      to={hrefs?.[item.href] ?? (item.href === "/" ? monitoringHref : item.href)}
      aria-current={isActiveApplicationPath(pathname, item.href) ? "page" : undefined}
      onClick={event => {
        if (item.href === "/") onMonitoringClick?.(event);
        if (!event.defaultPrevented) onNavigate?.(event);
      }}>
      <item.icon size={16} strokeWidth={1.6} aria-hidden="true" /><span>{item.label}</span>
    </Link>)}
  </div>;
}
