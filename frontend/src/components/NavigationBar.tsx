import { useCallback, useContext, useEffect, useState } from "react";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";
import { Sheet, SheetTrigger } from "@/components/ui/sheet";
import { buttonVariants } from "./ui/button";
import { Menu } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Button } from "./ui/button";
import { useAuth } from "@/auth/AuthContext";
import { Link, useNavigate } from "react-router-dom";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ModeToggle } from "./mode-toggle";
import { FetchContext } from "@/dataFetch/FetchContext";

interface RouteProps {
  href: string;
  label: string;
}

const routeList: RouteProps[] = [];

export const NavigationBar = () => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const { isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const [message, setMessage] = useState<string>("");
  const [anomalyCount, setAnomalyCount] = useState<number>(0);
  const fetchContext = useContext(FetchContext);

  const handleLogout = () => {
    logout();
    setMessage("Logout erfolgreich.");
    setTimeout(() => {
      navigate("/login");
    }, 1500);
  };

  const refreshAnomalyCount = useCallback(async () => {
    if (!fetchContext || !isAuthenticated) {
      setAnomalyCount(0);
      return;
    }

    try {
      const chargers = await fetchContext.getAllChargers();
      if (!chargers.length) {
        setAnomalyCount(0);
        return;
      }

      const anomaliesByCharger = await Promise.all(
        chargers.map((charger) => fetchContext.getAnomalies(charger.charger_id))
      );
      const total = anomaliesByCharger.reduce(
        (sum, anomalies) => sum + anomalies.length,
        0
      );
      setAnomalyCount(total);
    } catch (err) {
      console.error("Failed to refresh anomaly badge count:", err);
    }
  }, [fetchContext, isAuthenticated]);

  useEffect(() => {
    void refreshAnomalyCount();

    if (!fetchContext || !isAuthenticated) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshAnomalyCount();
    }, 30000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [fetchContext, isAuthenticated, refreshAnomalyCount]);

  return (
    <header className="sticky border-b-[1px] top-0 z-40 w-full bg-white dark:border-b-slate-700 dark:bg-background">
      {message && (
        <div className="bg-green-100 text-green-800 p-2 text-center">
          {message}
        </div>
      )}
      <NavigationMenu className="w-full flex">
        <NavigationMenuList className="h-14 px-4 w-screen flex items-center justify-start space-x-10">

          {/* Logo */}
          <NavigationMenuItem className="font-bold flex">
            <Link
              to="/"
              rel="noreferrer noopener"
              className="ml-2 font-bold text-xl flex"
            >
              off/key
            </Link>
          </NavigationMenuItem>

          {/* Home */}
          <NavigationMenuItem>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link to="/" className="flex items-center">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none"
                    viewBox="0 0 24 24" strokeWidth={1.5}
                    stroke="currentColor" className="size-6">
                    <path strokeLinecap="round" strokeLinejoin="round"
                      d="m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
                  </svg>
                </Link>
              </TooltipTrigger>
              <TooltipContent>Home</TooltipContent>
            </Tooltip>
          </NavigationMenuItem>

          {/* Favourites */}
          <NavigationMenuItem>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link to="/favourites" className="flex items-center">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none"
                    viewBox="0 0 24 24" strokeWidth={1.5}
                    stroke="currentColor" className="size-6">
                    <path strokeLinecap="round" strokeLinejoin="round"
                      d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
                  </svg>
                </Link>
              </TooltipTrigger>
              <TooltipContent>Favorites</TooltipContent>
            </Tooltip>
          </NavigationMenuItem>

          {/* Anomalies */}
          <NavigationMenuItem>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link to="/anomalies" className="relative flex items-center">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none"
                    viewBox="0 0 24 24" strokeWidth={1.5}
                    stroke="currentColor" className="size-6">
                    <path strokeLinecap="round" strokeLinejoin="round"
                      d="M3 3v1.5M3 21v-6m0 0 2.77-.693a9 9 0 0 1 6.208.682l.108.054a9 9 0 0 0 6.086.71l3.114-.732a48.524 48.524 0 0 1-.005-10.499l-3.11.732a9 9 0 0 1-6.085-.711l-.108-.054a9 9 0 0 0-6.208-.682L3 4.5M3 15V4.5" />
                  </svg>
                  {anomalyCount > 0 && (
                    <span className="absolute -top-2 -right-3 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-none text-white">
                      {anomalyCount > 99 ? "99+" : anomalyCount}
                    </span>
                  )}
                </Link>
              </TooltipTrigger>
              <TooltipContent>Anomalies</TooltipContent>
            </Tooltip>
          </NavigationMenuItem>

          {/* Theme + User */}
          <NavigationMenuItem className="ml-auto flex items-center gap-4">
            {/* Theme Toggle */}
            <ModeToggle />

            {/* User */}
            {isAuthenticated ? (
              <DropdownMenu>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <button className="flex items-center justify-center cursor-pointer">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none"
                          viewBox="0 0 24 24" strokeWidth={1.5}
                          stroke="currentColor" className="size-6">
                          <path strokeLinecap="round" strokeLinejoin="round"
                            d="M17.982 18.725A7.488 7.488 0 0 0 12 15.75a7.488 7.488 0 0 0-5.982 2.975m11.963 0a9 9 0 1 0-11.963 0m11.963 0A8.966 8.966 0 0 1 12 21a8.966 8.966 0 0 1-5.982-2.275M15 9.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                        </svg>
                      </button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                  <TooltipContent>User Menu</TooltipContent>
                </Tooltip>

                <DropdownMenuContent>
                  <DropdownMenuItem
                    onClick={() => navigate("/account")}
                    className="flex items-center gap-2 cursor-pointer"
                  >
                    Mein Account
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleLogout}>
                    Logout
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Link to="/login">
                <Button className="bg-black">Login</Button>
              </Link>
            )}
          </NavigationMenuItem>

          {/* Mobile Menu */}
          <span className="flex md:hidden">
            <Sheet open={isOpen} onOpenChange={setIsOpen}>
              <SheetTrigger className="px-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Menu
                      className="flex md:hidden h-5 w-5"
                      onClick={() => setIsOpen(true)}
                    />
                  </TooltipTrigger>
                  <TooltipContent>Menü</TooltipContent>
                </Tooltip>
              </SheetTrigger>
            </Sheet>
          </span>

          {/* Desktop Navigation (optional) */}
          <nav className="hidden md:flex gap-2">
            {routeList.map((route: RouteProps, i) => (
              <a
                rel="noreferrer noopener"
                href={route.href}
                key={i}
                className={`text-[17px] ${buttonVariants({ variant: "ghost" })}`}
              >
                {route.label}
              </a>
            ))}
          </nav>
        </NavigationMenuList>
      </NavigationMenu>
    </header>
  );
};
