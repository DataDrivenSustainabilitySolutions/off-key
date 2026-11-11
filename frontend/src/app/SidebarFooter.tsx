import { ChevronsUpDown } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { memberInitials } from "@/lib/utils";
import { ApplicationMenu } from "./ApplicationMenu";

/** The account menu, including settings, anchored below the scrolling catalogue. */
export function SidebarFooter({ onNavigate }: { onNavigate?: () => void }) {
  const { member, isAuthenticated } = useAuth();
  return <div className="app-sidebar-footer">
    <ApplicationMenu side="top" align="start" onSettings={onNavigate} trigger={isAuthenticated
      ? <button type="button" className="app-menu-trigger app-sidebar-item app-sidebar-account" aria-label="Account menu" title={member?.email}>
        <span className="app-avatar" aria-hidden="true">{memberInitials(member?.email)}</span>
        <span>{member?.email ?? "Account"}</span>
        <ChevronsUpDown size={14} aria-hidden="true" />
      </button> : undefined} />
  </div>;
}
