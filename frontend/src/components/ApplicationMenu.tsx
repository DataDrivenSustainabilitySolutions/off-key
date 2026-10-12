import type { ReactElement } from "react";
import { ChevronDown, Grid2X2, LogIn, LogOut, Settings2, UserCircle } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { applicationNavItems, isActiveApplicationPath } from "./application-navigation";

type Props = {
  navigation?: boolean;
  trigger?: ReactElement;
};

/** Application navigation and account actions shared by every page. */
export function ApplicationMenu({ navigation = true, trigger }: Props) {
  const { isAuthenticated, member, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  if (!isAuthenticated) return <Button asChild size="sm"><Link to="/login"><LogIn className="size-4" />Login</Link></Button>;
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>{trigger ?? <button className="app-menu-trigger" aria-label="Application menu"><Grid2X2 size={16} /><span>Menu</span><ChevronDown size={12} /></button>}</DropdownMenuTrigger>
    <DropdownMenuContent align="end" sideOffset={8} className="app-popover app-menu">
      {navigation && <>
        {applicationNavItems.map((item) => <DropdownMenuItem asChild key={item.href} className="app-menu-item">
          <Link to={item.href} aria-current={isActiveApplicationPath(location.pathname, item.href) ? "page" : undefined}>
            <item.icon className="size-4" />{item.label}
          </Link>
        </DropdownMenuItem>)}
        <div role="separator" className="app-menu-separator" />
      </>}
      {member && <p className="app-menu-account" title={member.email}>{member.email}</p>}
      <DropdownMenuItem asChild className="app-menu-item"><Link to="/account" aria-current={location.pathname === "/account" ? "page" : undefined}><UserCircle className="size-4" />Account</Link></DropdownMenuItem>
      <DropdownMenuItem asChild className="app-menu-item"><Link to="/account/settings" aria-current={location.pathname === "/account/settings" ? "page" : undefined}><Settings2 className="size-4" />Settings</Link></DropdownMenuItem>
      <DropdownMenuItem className="app-menu-item" onSelect={() => { logout(); navigate("/login", { replace: true }); }}><LogOut className="size-4" />Logout</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>;
}
