export interface Member {
  id: number;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}
