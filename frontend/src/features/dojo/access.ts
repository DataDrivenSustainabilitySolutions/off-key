import { useAuth } from "@/auth/AuthContext";

/** Whether the signed-in member's role grants the Dojo permission. */
export function useDojoAccess() {
  const { can } = useAuth();
  return can("use_dojo");
}
