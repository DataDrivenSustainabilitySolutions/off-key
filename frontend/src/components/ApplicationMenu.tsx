import { useRef, useState, type ReactElement } from "react";
import { Activity, ChevronDown, Grid2X2, LogIn, LogOut, Settings2, UserCircle } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { SettingsDialog } from "@/features/settings/SettingsDialog";
import { useOptionalCatalogue } from "@/features/workspace/catalogue-context";

type Props = {
  trigger?: ReactElement;
};

/** Preferences, account actions and operational status shared by every page. */
export function ApplicationMenu({ trigger }: Props) {
  const { isAuthenticated, member, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const catalogue = useOptionalCatalogue();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const openingSettings = useRef(false);

  if (!isAuthenticated) {
    return <Button asChild size="sm"><Link to="/login"><LogIn className="size-4" />Log in</Link></Button>;
  }

  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild ref={menuTrigger}>
        {trigger ?? <button className="app-menu-trigger" aria-label="Application menu">
          <Grid2X2 size={16} /><span>Menu</span><ChevronDown size={12} />
        </button>}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="app-popover app-menu"
        onCloseAutoFocus={event => {
          // Let the settings dialog take focus as the menu closes.
          if (openingSettings.current) {
            event.preventDefault();
            openingSettings.current = false;
          }
        }}>
        {member && <p className="app-menu-account" title={member.email}>{member.email}</p>}
        <DropdownMenuItem asChild className="app-menu-item">
          <Link to={catalogue?.sectionHref("/account") ?? "/account"} aria-current={location.pathname === "/account" ? "page" : undefined}>
            <UserCircle className="size-4" />Account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem className="app-menu-item" aria-haspopup="dialog" onSelect={() => {
          openingSettings.current = true;
          setSettingsOpen(true);
        }}><Settings2 className="size-4" />Settings</DropdownMenuItem>
        <DropdownMenuItem asChild className="app-menu-item">
          <Link to={catalogue?.sectionHref("/system/status") ?? "/system/status"} aria-current={location.pathname === "/system/status" ? "page" : undefined}>
            <Activity className="size-4" />System status
          </Link>
        </DropdownMenuItem>
        <div role="separator" className="app-menu-separator" />
        <DropdownMenuItem className="app-menu-item" onSelect={() => {
          logout();
          navigate("/login", { replace: true });
        }}><LogOut className="size-4" />Log out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} onCloseAutoFocus={event => {
      event.preventDefault();
      // Radix defers this callback; preserve a newer focus choice after close.
      if (document.activeElement === document.body) menuTrigger.current?.focus();
    }} />
  </>;
}
