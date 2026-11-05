export type Permission = "manage_sources" | "manage_monitors" | "manage_alarms" | "manage_members";

export interface Member {
  id: number;
  email: string;
  /** The id of the member's role, as `/v1/roles` lists it. */
  role: string;
  /** What the member may change; every member can read. */
  permissions: Permission[];
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface PermissionInfo {
  id: Permission;
  description: string;
}

export interface Role {
  id: string;
  name: string;
  permissions: Permission[];
  /** False for `admin`, which always holds every permission. */
  editable: boolean;
  /** `admin` and `user` cannot be deleted. */
  built_in: boolean;
  /** Members and pending invitations holding the role. */
  members: number;
}
