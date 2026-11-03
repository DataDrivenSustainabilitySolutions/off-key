import { lazy, Suspense, useEffect, useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Activity, Database, SlidersHorizontal, UserCircle, X, type LucideIcon } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { useOverlayDocumentTitle } from "@/hooks/use-document-title";
import { settingsHref, settingsReturnFocus, useSettingsNavigation, type SettingsSection } from "@/lib/settings-navigation";
import { useOptionalCatalogue } from "@/features/workspace/catalogue-context";
import { AppearanceSettings } from "@/features/settings/AppearanceSettings";
import "@/features/settings/settings.css";

const AccountSettings = lazy(() => import("@/features/account/AccountSettings"));
const CatalogueSettings = lazy(() => import("@/features/workspace/CatalogueSettingsSection"));
const SystemStatusSettings = lazy(() => import("@/features/settings/SystemStatusSettings"));

type SectionDefinition = {
  id: SettingsSection;
  label: string;
  description: string;
  icon: LucideIcon;
  group: "Personal" | "Workspace";
  /** Hidden from signed-out visitors. */
  membersOnly?: boolean;
  content: () => ReactNode;
};

const SECTIONS: SectionDefinition[] = [
  { id: "account", label: "Account", description: "Your sign-in and who can access this organization.", icon: UserCircle,
    group: "Personal", membersOnly: true, content: () => <AccountSettings /> },
  { id: "preferences", label: "Preferences", description: "Choose how Aberration looks on this device.", icon: SlidersHorizontal,
    group: "Personal", content: () => <AppearanceSettings /> },
  { id: "catalogue", label: "Catalogue", description: "Manage your sources and catalogue files.", icon: Database,
    group: "Workspace", content: () => <CatalogueSettings /> },
  { id: "status", label: "System status", description: "Live collection and storage diagnostics.", icon: Activity,
    group: "Workspace", membersOnly: true, content: () => <SystemStatusSettings /> },
];

/**
 * Account, preferences, catalogue and system status in one overlay above the
 * current page. The page underneath stays mounted, so closing returns to it as it was.
 */
export function SettingsOverlay() {
  const { section, select, close } = useSettingsNavigation();
  const { isAuthenticated } = useAuth();
  const catalogue = useOptionalCatalogue();
  const location = useLocation();
  const navigate = useNavigate();
  const saving = !!catalogue?.system.saving;
  const sections = SECTIONS.filter(entry => !entry.membersOnly || isAuthenticated);
  const current = sections.find(entry => entry.id === section);
  useOverlayDocumentTitle(current?.label);
  const dialog = useRef<HTMLDivElement>(null);
  const inOtherDialog = (target: EventTarget | null) => target instanceof Element
    && !dialog.current?.contains(target) && !!target.closest("[role=dialog], [role=alertdialog]");
  const nav = useRef<HTMLElement>(null);
  // On phones the sections scroll sideways; keep the open one in view.
  // Braced: browsers may return a promise from scrollIntoView, which an effect must not return.
  const revealSection = () => { nav.current?.querySelector<HTMLElement>("[aria-current]")?.scrollIntoView?.({ block: "nearest", inline: "nearest" }); };
  useEffect(() => { revealSection(); }, [current?.id]);

  // Earlier links opened catalogue settings with ?catalogue=settings.
  const legacyCatalogue = new URLSearchParams(location.search).get("catalogue") === "settings";
  useEffect(() => {
    if (!legacyCatalogue) return;
    const params = new URLSearchParams(location.search);
    params.delete("catalogue");
    navigate(settingsHref({ ...location, search: `?${params}` }, "catalogue"), { replace: true, state: location.state });
  }, [legacyCatalogue, location, navigate]);

  return <Dialog.Root open={!!current} onOpenChange={open => { if (!open && !saving) close(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="app-settings-overlay" />
      <Dialog.Content ref={dialog} className="app-settings-dialog"
        // Start on the window itself rather than lighting up the first section.
        onOpenAutoFocus={event => { event.preventDefault(); dialog.current?.focus(); revealSection(); }}
        // A dialog opened above the overlay (remove member, catalogue editor) handles its
        // own Escape and clicks; Radix can briefly count the overlay as topmost too.
        onEscapeKeyDown={event => { if (saving || inOtherDialog(event.target)) event.preventDefault(); }}
        onInteractOutside={event => { if (inOtherDialog(event.target)) event.preventDefault(); }}
        onCloseAutoFocus={event => {
          event.preventDefault();
          if (document.activeElement && document.activeElement !== document.body) return;
          (settingsReturnFocus() ?? document.querySelector<HTMLElement>(".app-menu-trigger"))?.focus();
        }}>
        <aside className="app-settings-sidebar">
          <Dialog.Title className="app-settings-title">Settings</Dialog.Title>
          <nav ref={nav} aria-label="Settings sections" className="app-settings-nav">
            {(["Personal", "Workspace"] as const).map(group => {
              const entries = sections.filter(entry => entry.group === group);
              return entries.length > 0 && <div key={group} className="app-settings-nav-group">
                <p className="app-settings-nav-label">{group}</p>
                {entries.map(({ id, label, icon: Icon }) => (
                  <button key={id} type="button" aria-current={id === current?.id ? "page" : undefined} onClick={() => select(id)}>
                    <Icon size={16} aria-hidden="true" />{label}
                  </button>
                ))}
              </div>;
            })}
          </nav>
        </aside>
        {current && <section key={current.id} className="app-settings-content" aria-labelledby="app-settings-heading">
          <header className="app-settings-heading">
            <h2 id="app-settings-heading">{current.label}</h2>
            <Dialog.Description>{current.description}</Dialog.Description>
          </header>
          <div className="app-settings-body">
            <Suspense fallback={<p role="status" className="app-settings-loading">Loading…</p>}>{current.content()}</Suspense>
          </div>
        </section>}
        <Dialog.Close className="app-settings-close" disabled={saving} aria-label="Close settings" title="Close settings">
          <X size={18} aria-hidden="true" />
        </Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
