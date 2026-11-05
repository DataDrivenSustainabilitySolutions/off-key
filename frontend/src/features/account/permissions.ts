import type { Permission } from "@/lib/member-api";

export const PERMISSION_LABELS: Record<Permission, string> = {
  manage_sources: "Manage sources",
  manage_monitors: "Manage monitors",
  manage_alarms: "Manage alarms",
  manage_members: "Manage members",
};

/** A role's permissions in a few words; every member can read. */
export const permissionSummary = (permissions: Permission[]) =>
  permissions.length ? permissions.map(permission => PERMISSION_LABELS[permission]).join(", ") : "View only";
