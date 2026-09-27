import { apiUtils } from "./api-client";

export interface Member {
  id: number;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export const getCurrentMember = () => apiUtils.get<Member>("/v1/members/me");
export const getMembers = () => apiUtils.get<Member[]>("/v1/members");
export const inviteMember = (email: string, role: Member["role"]) =>
  apiUtils.post<{ message: string }>("/v1/members/invitations", { email, role });
export const updateMember = (member: Member, changes: Partial<Pick<Member, "role" | "is_active">>) =>
  apiUtils.put<Member>(`/v1/members/${member.id}`, {
    role: member.role,
    is_active: member.is_active,
    ...changes,
  });
