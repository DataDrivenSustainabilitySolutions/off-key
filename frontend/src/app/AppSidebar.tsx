import type { Ref } from "react";
import { X } from "lucide-react";
import { BrandHome } from "@/components/BrandHome";
import { WORKSPACE_PATHS } from "@/features/workspace/application-navigation";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { SavedNavigation } from "@/features/workspace/SavedNavigation";
import { WorkspaceCatalogue } from "@/features/workspace/WorkspaceCatalogue";
import { SidebarFooter } from "./SidebarFooter";
import { SIDEBAR_ID, SidebarToggle } from "./SidebarToggle";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

type Props = {
  /** Hides the desktop sidebar, or closes the mobile drawer. */
  onHide: () => void;
  /** Called once a destination is chosen; the mobile drawer closes then. */
  onNavigate?: () => void;
  drawer?: boolean;
  hideRef?: Ref<HTMLButtonElement>;
  searchRef?: Ref<HTMLInputElement>;
};

/**
 * The application's one navigation spine: workspaces at the top, saved and
 * catalogue navigation in the middle, settings and account at the bottom.
 */
export function AppSidebar({ onHide, onNavigate, drawer, hideRef, searchRef }: Props) {
  const { sectionHref } = useCatalogue();
  return <div className="app-sidebar" id={SIDEBAR_ID}>
    <div className="app-sidebar-header">
      <BrandHome variant="wordmark" onNavigate={onNavigate} />
      {drawer
        ? <button ref={hideRef} type="button" className="app-sidebar-toggle" aria-label="Close navigation" onClick={onHide}><X size={16} aria-hidden="true" /></button>
        : <SidebarToggle ref={hideRef} open onClick={onHide} />}
    </div>
    <WorkspaceNavigation hrefs={Object.fromEntries(WORKSPACE_PATHS.map(path => [path, sectionHref(path)]))} onNavigate={onNavigate} />
    <div className="app-sidebar-body">
      <SavedNavigation onNavigate={onNavigate} />
      <WorkspaceCatalogue onDismiss={onNavigate} searchRef={searchRef} />
    </div>
    <SidebarFooter onNavigate={onNavigate} />
  </div>;
}
