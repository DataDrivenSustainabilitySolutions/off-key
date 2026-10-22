import { ExplorerWorkspace } from "@/features/explorer/ExplorerWorkspace";

// ApplicationWorkspace already remounts the workspace when the account changes.
export default function MonitoringWorkspace() {
  return <ExplorerWorkspace />;
}
