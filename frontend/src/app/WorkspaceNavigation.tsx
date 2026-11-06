import { Link, useLocation } from "react-router-dom";
import { isActiveApplicationPath, workspaceNavItems } from "../features/workspace/application-navigation";
import { useDojoAccess } from "../features/dojo/access";

export function WorkspaceNavigation({ hrefs }: { hrefs?: Record<string, string> }) {
  const { pathname } = useLocation();
  const dojo = useDojoAccess();
  return <div className="app-workspace-links" role="group" aria-label="Workspaces">
    {workspaceNavItems.filter(item => !item.dojo || dojo).map(item => <Link key={item.href} className="app-workspace-link"
      to={hrefs?.[item.href] ?? item.href}
      aria-current={isActiveApplicationPath(pathname, item.href) ? "page" : undefined}>
      <item.icon size={16} strokeWidth={1.6} aria-hidden="true" /><span>{item.label}</span>
    </Link>)}
  </div>;
}
