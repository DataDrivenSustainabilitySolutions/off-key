import { useRef } from "react";
import { ChevronsUpDown, Settings } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { memberInitials } from "@/lib/utils";
import { useSettingsNavigation } from "@/lib/settings-navigation";
import { ApplicationMenu } from "./ApplicationMenu";

/** Settings and the account menu, anchored below the scrolling catalogue. */
export function SidebarFooter({ onNavigate }: { onNavigate?: () => void }) {
  const { member, isAuthenticated } = useAuth();
  const settings = useSettingsNavigation();
  const button = useRef<HTMLButtonElement>(null);
  return <div className="app-sidebar-footer">
    <button ref={button} type="button" className="app-sidebar-item" aria-haspopup="dialog"
      onClick={() => { onNavigate?.(); settings.open("preferences", button.current); }}>
      <Settings size={16} strokeWidth={1.6} aria-hidden="true" /><span>Settings</span>
    </button>
    <ApplicationMenu side="top" align="start" onSettings={onNavigate} trigger={isAuthenticated
      ? <button type="button" className="app-menu-trigger app-sidebar-item app-sidebar-account" aria-label="Account menu" title={member?.email}>
        <span className="app-avatar" aria-hidden="true">{memberInitials(member?.email)}</span>
        <span>{member?.email ?? "Account"}</span>
        <ChevronsUpDown size={14} aria-hidden="true" />
      </button> : undefined} />
  </div>;
}
