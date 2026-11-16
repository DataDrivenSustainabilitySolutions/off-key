import { SourcesWorkspace } from "@/features/catalogue/SourcesWorkspace";
import { CopyToDojo } from "@/features/dojo/CopyToDojo";

// The selected source offers the same header actions as on Monitoring.
export default function SystemCatalogue() {
  return <SourcesWorkspace sourceActions={(scope, readings) => <CopyToDojo compact scope={scope} readings={readings} />} />;
}
