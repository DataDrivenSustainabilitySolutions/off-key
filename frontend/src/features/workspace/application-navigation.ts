import { AlertTriangle, Database, FlaskConical, Home, type LucideIcon } from "lucide-react";

export type ApplicationNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown only to members who may use it. */
  dojo?: boolean;
};

const monitoring: ApplicationNavItem = { href: "/", label: "Monitoring", icon: Home };
const sources: ApplicationNavItem = { href: "/sources", label: "Sources", icon: Database };

export const workspaceNavItems: ApplicationNavItem[] = [
  monitoring, sources,
  { href: "/anomalies", label: "Reporting", icon: AlertTriangle },
  { href: "/dojo", label: "Dojo", icon: FlaskConical, dojo: true },
];

export const WORKSPACE_PATHS = workspaceNavItems.map(item => item.href);

export function isActiveApplicationPath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  // Entity details are opened from Reporting events.
  if (href === "/anomalies" && pathname.startsWith("/details/")) return true;
  return pathname === href || pathname.startsWith(`${href}/`);
}
