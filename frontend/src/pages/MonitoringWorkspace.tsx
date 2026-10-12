import { useAuth } from "@/auth/AuthContext";
import { ExplorerWorkspace } from "@/features/explorer/ExplorerWorkspace";

export default function MonitoringWorkspace() {
  const { userId } = useAuth();
  return <ExplorerWorkspace key={userId ?? "local"} />;
}
