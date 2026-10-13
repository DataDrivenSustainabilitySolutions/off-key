import { useRef, useState, type MouseEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Menu, PanelLeft, X } from "lucide-react";
import { Outlet } from "react-router-dom";
import { AppHeader } from "./AppHeader";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

export function ApplicationWorkspace() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const closeAfterNavigation = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) setMobileOpen(false);
  };
  return <div className={`app-workspace-shell${sidebarOpen ? "" : " is-navigation-hidden"}`}>
    {sidebarOpen && <aside className="app-workspace-sidebar"><nav aria-label="Primary navigation"><WorkspaceNavigation /></nav></aside>}
    <div className="app-workspace-main">
      <AppHeader leading={<button ref={toggle} className="app-icon-button" aria-label="Toggle workspace navigation"
        onClick={() => window.matchMedia("(max-width: 760px)").matches ? setMobileOpen(true) : setSidebarOpen(value => !value)}>
        {sidebarOpen ? <PanelLeft size={19} /> : <Menu size={19} />}
      </button>} />
      <Outlet />
    </div>
    <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}><Dialog.Portal>
      <Dialog.Overlay className="app-workspace-overlay" />
      <Dialog.Content className="app-workspace-mobile" onCloseAutoFocus={event => { event.preventDefault(); toggle.current?.focus(); }}>
        <Dialog.Title className="sr-only">Workspace navigation</Dialog.Title>
        <Dialog.Description className="sr-only">Choose Monitoring, Data sources, or Anomalies.</Dialog.Description>
        <div className="app-workspace-mobile-top"><WorkspaceNavigation onNavigate={closeAfterNavigation} />
          <button className="app-icon-button" aria-label="Close workspace navigation" onClick={() => setMobileOpen(false)}><X size={18} /></button>
        </div>
      </Dialog.Content>
    </Dialog.Portal></Dialog.Root>
  </div>;
}
