import { AlertTriangle, Box, Database, Home, type LucideIcon } from "lucide-react";

export type ApplicationNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

const monitoring: ApplicationNavItem = { href: "/", label: "Monitoring", icon: Home };
const sources: ApplicationNavItem = { href: "/sources", label: "Data sources", icon: Database };

export const workspaceNavItems: ApplicationNavItem[] = [monitoring, sources];

export const applicationNavItems: ApplicationNavItem[] = [
  monitoring,
  { href: "/entities", label: "Entities", icon: Box },
  sources,
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle },
];

export function isActiveApplicationPath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/entities" && /^\/(details|monitoring)\//.test(pathname)) return true;
  return pathname === href || pathname.startsWith(`${href}/`);
}
