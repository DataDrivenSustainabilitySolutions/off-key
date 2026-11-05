import { apiUtils } from "./api-client";
import type { Member, Permission, PermissionInfo, Role } from "./member-types";
export type { Member, Permission, PermissionInfo, Role } from "./member-types";

export const getCurrentMember = () => apiUtils.get<Member>("/v1/members/me", { redirectOnUnauthorized: false });
export const getMembers = () => apiUtils.get<Member[]>("/v1/members");
export const inviteMember = (email: string, role: Member["role"]) =>
  apiUtils.post<{ message: string }>("/v1/members/invitations", { email, role });
export const updateMember = (member: Member, changes: Partial<Pick<Member, "role" | "is_active">>) =>
  apiUtils.put<Member>(`/v1/members/${member.id}`, {
    role: member.role,
    is_active: member.is_active,
    ...changes,
  });

export const removeMember = (memberId: number) =>
  apiUtils.delete<void>(`/v1/members/${memberId}`);

export const getPermissions = () => apiUtils.get<PermissionInfo[]>("/v1/permissions");
export const getRoles = () => apiUtils.get<Role[]>("/v1/roles");
export const createRole = (name: string, permissions: Permission[]) =>
  apiUtils.post<Role>("/v1/roles", { name, permissions });
export const updateRole = (roleId: string, changes: { name?: string; permissions?: Permission[] }) =>
  apiUtils.patch<Role>(`/v1/roles/${encodeURIComponent(roleId)}`, changes);
export const deleteRole = (roleId: string) =>
  apiUtils.delete<void>(`/v1/roles/${encodeURIComponent(roleId)}`);
