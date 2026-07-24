import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Home,
  LogIn,
  LogOut,
  Menu,
  ServerCog,
  Star,
  UserCircle,
} from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { getAnomalyCount } from "@/lib/charger-api";
import { clientLogger } from "@/lib/logger";
import { cn } from "@/lib/utils";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ModeToggle } from "./mode-toggle";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const primaryNavItems: NavItem[] = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/favourites", label: "Favorites", icon: Star },
  { href: "/services", label: "Services", icon: ServerCog },
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle },
];

const isActivePath = (pathname: string, href: string) =>
  href === "/" ? pathname === "/" : pathname.startsWith(href);

type NavLinkProps = {
  item: NavItem;
  active: boolean;
  badge?: number;
  onClick?: () => void;
  compact?: boolean;
};

function NavLinkItem({ item, active, badge, onClick, compact = false }: NavLinkProps) {
  const Icon = item.icon;

  const link = (
    <Link
      to={item.href}
      onClick={onClick}
      className={cn(
        "relative inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/65 hover:text-foreground",
        active && "bg-primary/[0.08] text-primary",
        compact && "w-full justify-start"
      )}
      aria-current={active ? "page" : undefined}
    >
      <Icon className={cn("h-4 w-4", active && "text-primary")} />
      {!compact ? <span className="hidden lg:inline">{item.label}</span> : item.label}
      {badge && badge > 0 ? (
        <span className="ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-[10px] font-semibold leading-none text-destructive-foreground">
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </Link>
  );

  if (compact) {
    return link;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent>{item.label}</TooltipContent>
    </Tooltip>
  );
}

export const NavigationBar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [message, setMessage] = useState("");
  const [anomalyCount, setAnomalyCount] = useState(0);
  const refreshInFlightRef = useRef(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const handleLogout = () => {
    logout();
    setMessage("Logout erfolgreich.");
    window.setTimeout(() => {
      navigate("/login");
    }, 1500);
  };

  const refreshAnomalyCount = useCallback(async () => {
    if (!isAuthenticated) {
      return;
    }

    if (refreshInFlightRef.current) {
      return;
    }
    refreshInFlightRef.current = true;

    try {
      const lastSeen =
        localStorage.getItem("off-key:last-seen-anomalies") ?? undefined;
      const total = await getAnomalyCount(lastSeen);
      if (isMountedRef.current) {
        setAnomalyCount(total);
      }
    } catch (err) {
      clientLogger.error({
        event: "anomalies.badge_refresh_failed",
        message: "Failed to refresh anomaly badge count",
        error: err,
      });
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [isAuthenticated]);

  const displayedAnomalyCount =
    isAuthenticated ? anomalyCount : 0;

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void refreshAnomalyCount();
    }, 0);

    if (!isAuthenticated) {
      return () => window.clearTimeout(timeoutId);
    }

    const intervalId = window.setInterval(() => {
      void refreshAnomalyCount();
    }, 30000);

    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };
  }, [isAuthenticated, refreshAnomalyCount]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void refreshAnomalyCount();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [location.pathname, refreshAnomalyCount]);

  useEffect(() => {
    const onFocus = () => {
      void refreshAnomalyCount();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void refreshAnomalyCount();
      }
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshAnomalyCount]);

  const navItems = useMemo(
    () =>
      primaryNavItems.map((item) => ({
        ...item,
        active: isActivePath(location.pathname, item.href),
        badge: item.href === "/anomalies" ? displayedAnomalyCount : undefined,
      })),
    [displayedAnomalyCount, location.pathname]
  );

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/90 backdrop-blur-xl supports-[backdrop-filter]:bg-background/78">
      {message ? (
        <div className="border-b border-emerald-200 bg-emerald-50 px-4 py-2 text-center text-sm font-medium text-emerald-800 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200">
          {message}
        </div>
      ) : null}
      <NavigationMenu className="w-full max-w-none justify-stretch">
        <NavigationMenuList className="mx-auto flex h-16 w-full max-w-7xl items-center justify-start gap-2 px-4 sm:px-6 lg:px-8">
          <NavigationMenuItem className="mr-2 flex shrink-0">
            <Link
              to="/"
              rel="noreferrer noopener"
              className="group flex items-center gap-2.5 rounded-lg py-1.5 pr-2 text-base font-semibold tracking-[-0.02em]"
            >
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-[11px] font-bold tracking-[-0.04em] text-primary-foreground shadow-sm transition-transform group-hover:scale-[1.03]">
                ok
              </span>
              <span>off<span className="text-primary">/</span>key</span>
            </Link>
          </NavigationMenuItem>

          <nav className="hidden min-w-0 flex-1 items-center gap-1 md:flex">
            {navItems.map((item) => (
              <NavigationMenuItem key={item.href}>
                <NavLinkItem
                  item={item}
                  active={item.active}
                  badge={item.badge}
                />
              </NavigationMenuItem>
            ))}
          </nav>

          <NavigationMenuItem className="ml-auto flex shrink-0 items-center justify-end gap-2">
            <ModeToggle />

            {isAuthenticated ? (
              <DropdownMenu>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" aria-label="User menu">
                        <UserCircle className="h-5 w-5" />
                      </Button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                  <TooltipContent>User Menu</TooltipContent>
                </Tooltip>

                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onClick={() => navigate("/account")}
                    className="cursor-pointer"
                  >
                    <UserCircle className="h-4 w-4" />
                    Account
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleLogout} className="cursor-pointer">
                    <LogOut className="h-4 w-4" />
                    Logout
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Button asChild size="sm">
                <Link to="/login">
                  <LogIn className="h-4 w-4" />
                  Login
                </Link>
              </Button>
            )}

            <Sheet open={isOpen} onOpenChange={setIsOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-80">
                <SheetHeader>
                  <SheetTitle>off/key</SheetTitle>
                  <SheetDescription>Navigation</SheetDescription>
                </SheetHeader>
                <nav className="flex flex-col gap-1 px-4">
                  {navItems.map((item) => (
                    <SheetClose asChild key={item.href}>
                      <NavLinkItem
                        item={item}
                        active={item.active}
                        badge={item.badge}
                        compact
                      />
                    </SheetClose>
                  ))}
                </nav>
              </SheetContent>
            </Sheet>
          </NavigationMenuItem>
        </NavigationMenuList>
      </NavigationMenu>
    </header>
  );
};
