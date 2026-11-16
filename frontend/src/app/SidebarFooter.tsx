import { ArrowLeft, ChevronsUpDown } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { memberInitials } from "@/lib/utils";
import { DEMO_VISITOR } from "@/auth/demo";
import { WEBSITE_URL } from "@/lib/website";
import { ApplicationMenu } from "./ApplicationMenu";

/**
 * The account menu, including settings, anchored below the scrolling catalogue.
 * Visitors of the public demo also get a way back to the website here.
 */
export function SidebarFooter({ onNavigate }: { onNavigate?: () => void }) {
  const { member, isAuthenticated, isGuest } = useAuth();
  // Visitors of the public demo get the same account row as a signed-in member.
  const name = isGuest ? DEMO_VISITOR.name : member?.email ?? "Account";
  return <div className="app-sidebar-footer">
    {isGuest && <a className="app-sidebar-item app-sidebar-website" href={WEBSITE_URL}>
      <ArrowLeft size={16} strokeWidth={1.6} aria-hidden="true" />
      <span>Back to website</span>
    </a>}
    <ApplicationMenu side="top" align="start" onSettings={onNavigate} trigger={isAuthenticated || isGuest
      ? <button type="button" className="app-menu-trigger app-sidebar-item app-sidebar-account" aria-label={isGuest ? "Demo menu" : "Account menu"} title={isGuest ? `${name} · Read only` : member?.email}>
        <span className="app-avatar" aria-hidden="true">{isGuest ? DEMO_VISITOR.initials : memberInitials(member?.email)}</span>
        <span>{name}</span>
        <ChevronsUpDown size={14} aria-hidden="true" />
      </button> : undefined} />
  </div>;
}
