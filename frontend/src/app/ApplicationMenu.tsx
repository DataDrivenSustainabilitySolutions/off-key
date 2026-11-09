import { useRef, type ReactElement } from "react";
import { Activity, Database, LogIn, LogOut, SlidersHorizontal, UserCircle } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { memberInitials } from "@/lib/utils";
import { useSettingsNavigation, type SettingsSection } from "@/lib/settings-navigation";

type Props = {
  trigger?: ReactElement;
  side?: "top" | "bottom";
  align?: "start" | "end";
  /** Called as a settings section opens, before the overlay takes focus. */
  onSettings?: () => void;
};

const items = [
  { section: "account", label: "Account", icon: UserCircle },
  { section: "preferences", label: "Preferences", icon: SlidersHorizontal },
  { section: "catalogue", label: "Catalogue", icon: Database },
  { section: "status", label: "System status", icon: Activity },
] as const satisfies ReadonlyArray<{ section: SettingsSection; label: string; icon: typeof UserCircle }>;

/** The account menu; each settings entry opens the settings overlay above the current page. */
export function ApplicationMenu({ trigger, side = "bottom", align = "end", onSettings }: Props) {
  const { isAuthenticated, member, logout } = useAuth();
  const navigate = useNavigate();
  const settings = useSettingsNavigation();
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const openingSettings = useRef(false);

  if (!isAuthenticated) {
    return <Button asChild size="sm"><Link to="/login"><LogIn className="size-4" />Log in</Link></Button>;
  }

  return <DropdownMenu>
    <DropdownMenuTrigger asChild ref={menuTrigger}>
      {trigger ?? <button className="app-menu-trigger app-avatar-trigger" aria-label="Account menu" title={member?.email}>
        <span className="app-avatar" aria-hidden="true">{memberInitials(member?.email)}</span>
      </button>}
    </DropdownMenuTrigger>
    <DropdownMenuContent side={side} align={align} sideOffset={8} className="app-popover app-menu z-[90]"
      onCloseAutoFocus={event => {
        // Let the settings overlay take focus as the menu closes.
        if (openingSettings.current) {
          event.preventDefault();
          openingSettings.current = false;
        }
      }}>
      {member && <p className="app-menu-account" title={member.email}>{member.email}</p>}
      {items.map(({ section, label, icon: Icon }) => (
        <DropdownMenuItem key={section} className="app-menu-item" aria-haspopup="dialog" onSelect={() => {
          openingSettings.current = true;
          onSettings?.();
          settings.open(section, menuTrigger.current);
        }}><Icon className="size-4" />{label}</DropdownMenuItem>
      ))}
      <div role="separator" className="app-menu-separator" />
      <DropdownMenuItem className="app-menu-item" onSelect={() => {
        logout();
        navigate("/login", { replace: true });
      }}><LogOut className="size-4" />Log out</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>;
}
