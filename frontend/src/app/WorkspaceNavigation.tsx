import { useId, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { isActiveApplicationPath, workspaceNavItems } from "../features/workspace/application-navigation";
import { useDojoAccess } from "../features/dojo/access";

/** The workspace destinations, at the top of the sidebar. */
export function WorkspaceNavigation({ hrefs, onNavigate, toggle }: { hrefs?: Record<string, string>; onNavigate?: () => void; toggle: ReactNode }) {
  const { pathname } = useLocation();
  const dojo = useDojoAccess();
  const heading = useId();
  return <nav className="app-sidebar-workspaces" aria-labelledby={heading}>
    <div className="app-sidebar-heading-row">
      <h2 id={heading} className="app-sidebar-heading">Workspace</h2>
      {toggle}
    </div>
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
