import type { ReactNode } from "react";
import { ApplicationMenu } from "./ApplicationMenu";
import { BrandHome } from "../components/BrandHome";

type Props = {
  leading?: ReactNode;
  navigation?: ReactNode;
};

export function AppHeader({ leading, navigation }: Props) {
  return <header className="app-header" data-testid="application-header">
    <div className="app-header-leading"><BrandHome />{leading}</div>
    {navigation && <nav className="app-primary-nav" aria-label="Primary navigation">{navigation}</nav>}
    <div className="app-header-actions" data-testid="navbar-actions">
      <ApplicationMenu />
    </div>
  </header>;
}
