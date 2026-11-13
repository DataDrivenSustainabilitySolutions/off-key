import { Suspense, useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { CatalogueProvider } from "@/features/workspace/CatalogueProvider";
import { CatalogueDialogs } from "@/features/workspace/CatalogueDialogs";
import { useCatalogue } from "@/features/workspace/catalogue-context";
import { ExplorerSidebarResize } from "@/features/workspace/ExplorerSidebarResize";
import { DEFAULT_SIDEBAR_WIDTH } from "@/features/workspace/sidebarSizing";
import "@/features/explorer/explorer.css";
import "@/features/workspace/workspace.css";
import { MonitoringServicesProvider } from "@/domain/monitoring/MonitoringServicesProvider";
import { settingsSectionOf } from "@/lib/settings-navigation";
import { AppSidebar } from "./AppSidebar";
import { SettingsOverlay } from "./SettingsOverlay";
import { SidebarToggle } from "./SidebarToggle";

const MOBILE_QUERY = "(max-width: 760px)";
const subscribeMobile = (listener: () => void) => {
  const media = window.matchMedia(MOBILE_QUERY);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
const isMobile = () => window.matchMedia(MOBILE_QUERY).matches;
/** Runs after the sidebar has rendered open, two frames later. */
const afterLayout = (action: () => void) => requestAnimationFrame(() => requestAnimationFrame(action));

function WorkspaceFrame() {
  const { preferences, setPreferences, dialog, stored, favouritesError } = useCatalogue();
  const { pathname, search } = useLocation();
  const mobile = useSyncExternalStore(subscribeMobile, isMobile, () => false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const open = mobile ? drawerOpen : preferences.sidebarOpen;
  const show = useRef<HTMLButtonElement>(null);
  const hide = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLDivElement>(null);
  useEffect(() => { if (main.current) main.current.scrollTop = 0; }, [pathname]);

  const setDesktopOpen = (sidebarOpen: boolean) => {
    setPreferences(previous => ({ ...previous, sidebarOpen }));
    // Keep focus on the control that now toggles the sidebar.
    afterLayout(() => (sidebarOpen ? hide : show).current?.focus());
  };
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k" || event.altKey || event.shiftKey) return;
      event.preventDefault();
      if (mobile) setDrawerOpen(true);
      else if (!preferences.sidebarOpen) setPreferences(previous => ({ ...previous, sidebarOpen: true }));
      const focus = () => { searchInput.current?.focus(); searchInput.current?.select(); };
      if (open) focus();
      else afterLayout(focus);
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [mobile, open, preferences.sidebarOpen, setPreferences]);

  const width = preferences.sidebarWidth ?? DEFAULT_SIDEBAR_WIDTH;
  return <div className={`ex-shell app-shell${!mobile && !preferences.sidebarOpen ? " is-sidebar-hidden" : ""}`}
    style={{ "--ex-sidebar-width": `${width}px` } as CSSProperties}>
    {!mobile && <aside className="ex-sidebar-dock app-sidebar-dock" aria-label="Sidebar" inert={!preferences.sidebarOpen}>
      <AppSidebar onHide={() => setDesktopOpen(false)} hideRef={hide} searchRef={searchInput} />
      {preferences.sidebarOpen && <ExplorerSidebarResize width={width}
        onCommit={sidebarWidth => setPreferences(previous => ({ ...previous, sidebarWidth }))} />}
    </aside>}
    <div className="app-main-column">
      {(mobile || !preferences.sidebarOpen) && <div className="app-sidebar-reopen">
        <SidebarToggle ref={show} open={false} onClick={() => mobile ? setDrawerOpen(true) : setDesktopOpen(true)} />
      </div>}
      <div ref={main} className="ex-main app-main">
        {!stored && <p className="ex-banner" role="status">Browser storage is unavailable. Your navigation will last for this session.</p>}
        {favouritesError && <p className="ex-banner" role="status">{favouritesError}</p>}
        <Suspense fallback={<p className="workspace-loading" role="status">Loading page…</p>}><Outlet /></Suspense>
      </div>
    </div>
    <Dialog.Root open={mobile && drawerOpen} onOpenChange={setDrawerOpen}><Dialog.Portal>
      <Dialog.Overlay className="ex-dialog-overlay app-drawer-overlay" />
      <Dialog.Content ref={drawer} className="ex-mobile-sidebar app-drawer"
        onOpenAutoFocus={event => { event.preventDefault(); drawer.current?.focus(); }}
        onCloseAutoFocus={event => {
          event.preventDefault();
          // A settings overlay or editor opened from the drawer takes focus instead.
          if (!dialog && !settingsSectionOf(search)) show.current?.focus();
        }}>
        <Dialog.Title className="ex-sr-only">Navigation</Dialog.Title>
        <Dialog.Description className="ex-sr-only">Workspaces, favourites, collections and the catalogue of brokers, devices, topics and readings.</Dialog.Description>
        <AppSidebar drawer onHide={() => setDrawerOpen(false)} onNavigate={() => setDrawerOpen(false)} searchRef={searchInput} />
      </Dialog.Content>
    </Dialog.Portal></Dialog.Root>
    <SettingsOverlay />
    <CatalogueDialogs toggle={show} />
  </div>;
}

export function ApplicationWorkspace() {
  const { userId, isAuthenticated, isGuest } = useAuth();
  return <CatalogueProvider key={isGuest ? "demo" : userId ?? "local"}>
    <MonitoringServicesProvider enabled={isAuthenticated || isGuest}><WorkspaceFrame /></MonitoringServicesProvider>
  </CatalogueProvider>;
}
