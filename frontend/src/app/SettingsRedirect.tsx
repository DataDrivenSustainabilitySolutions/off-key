import { Navigate, useLocation } from "react-router-dom";
import { settingsHref, type SettingsSection } from "@/lib/settings-navigation";

/** Former settings pages open their overlay section above Monitoring, keeping the query. */
export function SettingsRedirect({ section }: { section: SettingsSection }) {
  const { search, hash } = useLocation();
  return <Navigate to={settingsHref({ pathname: "/", search, hash }, section)} replace />;
}
