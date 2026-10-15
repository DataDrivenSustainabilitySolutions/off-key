import { apiUtils } from "./api-client";
import type { Member } from "./member-types";
export type { Member } from "./member-types";

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
