import { useId } from "react";
import { Link, useLocation } from "react-router-dom";
import { isActiveApplicationPath, workspaceNavItems } from "../features/workspace/application-navigation";
import { useDojoAccess } from "../features/dojo/access";

/** The workspace destinations, at the top of the sidebar. */
export function WorkspaceNavigation({ hrefs, onNavigate }: { hrefs?: Record<string, string>; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const dojo = useDojoAccess();
  const heading = useId();
  return <nav className="app-sidebar-workspaces" aria-labelledby={heading}>
    <h2 id={heading} className="app-sidebar-heading">Workspace</h2>
    <ul className="app-sidebar-items">
      {workspaceNavItems.filter(item => !item.dojo || dojo).map(item => <li key={item.href}>
        <Link className="app-sidebar-item" to={hrefs?.[item.href] ?? item.href} onClick={onNavigate}
          aria-current={isActiveApplicationPath(pathname, item.href) ? "page" : undefined}>
          <item.icon size={16} strokeWidth={1.6} aria-hidden="true" /><span>{item.label}</span>
        </Link>
      </li>)}
    </ul>
  </nav>;
}
