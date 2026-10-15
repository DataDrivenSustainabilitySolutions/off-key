import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApplicationMenu } from "./ApplicationMenu";

type Props = {
  leading?: ReactNode;
  navigation?: ReactNode;
};

export function AppHeader({ leading, navigation }: Props) {
  return <header className="app-header" data-testid="application-header">
    <div className="app-header-leading">
      {leading ?? <Link to="/" className="app-brand font-mono">aberration</Link>}
    </div>
    {navigation && <nav className="app-primary-nav" aria-label="Primary navigation">{navigation}</nav>}
    <div className="app-header-actions" data-testid="navbar-actions">
      <ApplicationMenu />
    </div>
  </header>;
}
