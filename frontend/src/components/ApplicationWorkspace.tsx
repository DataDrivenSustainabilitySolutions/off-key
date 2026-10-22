import { Suspense, useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AppHeader } from "./AppHeader";
import { CatalogueToggle } from "./CatalogueToggle";
import { WorkspaceNavigation } from "./WorkspaceNavigation";
import { WORKSPACE_PATHS } from "./application-navigation";
import { CatalogueProvider } from "@/features/workspace/CatalogueProvider";
import { CatalogueDialogs } from "@/features/workspace/CatalogueDialogs";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { WorkspaceCatalogue } from "@/features/workspace/WorkspaceCatalogue";
import { ExplorerSidebarResize } from "@/features/explorer/ExplorerSidebarResize";
import { DEFAULT_SIDEBAR_WIDTH } from "@/features/explorer/sidebarSizing";
import "@/features/explorer/explorer.css";
import "@/features/workspace/workspace.css";

const subscribeMobile = (listener: () => void) => {
  const media = window.matchMedia("(max-width: 760px)");
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
const isMobile = () => window.matchMedia("(max-width: 760px)").matches;

function WorkspaceFrame() {
  const { preferences, setPreferences, sectionHref, dialog, stored } = useCatalogue();
  const { pathname } = useLocation();
  const mobile = useSyncExternalStore(subscribeMobile, isMobile, () => false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const mobileDrawer = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLDivElement>(null);
  useEffect(() => { if (main.current) main.current.scrollTop = 0; }, [pathname]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
      if (mobile ? mobileOpen : preferences.sidebarOpen) return;
      event.preventDefault();
      if (mobile) setMobileOpen(true);
      else setPreferences(previous => ({ ...previous, sidebarOpen: true }));
      requestAnimationFrame(() => requestAnimationFrame(() => window.document.querySelector<HTMLInputElement>(".ex-search input")?.focus()));
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [mobile, mobileOpen, preferences.sidebarOpen, setPreferences]);
  return <div className={`ex-shell app-catalogue-shell${!mobile && !preferences.sidebarOpen ? " ex-sidebar-hidden" : ""}`}
    style={{ "--ex-sidebar-width": `${preferences.sidebarWidth ?? DEFAULT_SIDEBAR_WIDTH}px` } as CSSProperties}>
    <AppHeader navigation={<WorkspaceNavigation hrefs={Object.fromEntries(WORKSPACE_PATHS.map(path => [path, sectionHref(path)]))} />} />
    <div className="app-catalogue-workspace">
      {!mobile && <aside className="ex-sidebar-dock app-catalogue-sidebar" inert={!preferences.sidebarOpen} aria-hidden={!preferences.sidebarOpen}>
        <div className="app-catalogue-sidebar-content"><WorkspaceCatalogue /></div>
        {preferences.sidebarOpen && <ExplorerSidebarResize width={preferences.sidebarWidth ?? DEFAULT_SIDEBAR_WIDTH}
          onCommit={sidebarWidth => setPreferences(previous => ({ ...previous, sidebarWidth }))} />}
      </aside>}
      <CatalogueToggle ref={toggle} className="catalogue-workspace-toggle" open={mobile ? mobileOpen : preferences.sidebarOpen}
        hidden={mobile && mobileOpen} onClick={() => mobile ? setMobileOpen(true)
          : setPreferences(previous => ({ ...previous, sidebarOpen: !previous.sidebarOpen }))} />
      <div ref={main} className="ex-main app-catalogue-main">
        {!stored && <p className="ex-banner" role="status">Browser storage is unavailable. Your navigation will last for this session.</p>}
        <Suspense fallback={<p className="workspace-loading" role="status">Loading page…</p>}><Outlet /></Suspense>
      </div>
    </div>
    <Dialog.Root open={mobile && mobileOpen} onOpenChange={setMobileOpen}><Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay app-catalogue-mobile-overlay" />
      <Dialog.Content ref={mobileDrawer} className="ex-mobile-sidebar app-catalogue-mobile-sidebar"
        onOpenAutoFocus={event => { event.preventDefault(); mobileDrawer.current?.focus(); }}
        onCloseAutoFocus={event => { event.preventDefault(); setMobileOpen(false); if (!dialog) toggle.current?.focus(); }}>
        <Dialog.Title className="ex-sr-only">MQTT catalogue</Dialog.Title>
        <Dialog.Description className="ex-sr-only">Browse brokers, entities, topics and readings for the current section.</Dialog.Description>
        <WorkspaceCatalogue onDismiss={() => setMobileOpen(false)} />
      </Dialog.Content>
    </Dialog.Portal></Dialog.Root>
    <CatalogueDialogs toggle={toggle} />
  </div>;
}

export function ApplicationWorkspace() {
  const { userId } = useAuth();
  return <CatalogueProvider key={userId ?? "local"}><WorkspaceFrame /></CatalogueProvider>;
}
