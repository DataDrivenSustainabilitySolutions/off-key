import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApplicationMenu } from "./ApplicationMenu";
import { ModeToggle } from "./mode-toggle";

type Props = {
  leading?: ReactNode;
};

export function AppHeader({ leading }: Props) {
  return <header className="app-header" data-testid="application-header">
    <div className="app-header-leading">
      {leading ?? <Link to="/" className="app-brand font-mono">aberration</Link>}
    </div>
    <div className="app-header-actions" data-testid="navbar-actions">
      <ModeToggle />
      <ApplicationMenu />
    </div>
  </header>;
}
