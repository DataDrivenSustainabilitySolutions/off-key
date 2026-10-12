import { AlertTriangle, Box, Database, Home, type LucideIcon } from "lucide-react";

export type ApplicationNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

export const applicationNavItems: ApplicationNavItem[] = [
  { href: "/", label: "Monitoring", icon: Home },
  { href: "/entities", label: "Entities", icon: Box },
  { href: "/sources", label: "Sources", icon: Database },
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle },
];

export function isActiveApplicationPath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/entities" && /^\/(details|monitoring)\//.test(pathname)) return true;
  return pathname === href || pathname.startsWith(`${href}/`);
}
