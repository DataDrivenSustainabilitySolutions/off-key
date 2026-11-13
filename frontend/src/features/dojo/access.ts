import { useAuth } from "@/auth/AuthContext";

/** Members with the Dojo permission and public guests can inspect datasets. */
export function useDojoAccess() {
  const { can, isGuest } = useAuth();
  return isGuest || can("use_dojo");
}
