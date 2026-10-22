import { Plus } from "lucide-react";
import { Breadcrumb } from "@/components/Breadcrumb";
import type { PipelineCatalog } from "./contracts";
import { PipelineDesignBrowser } from "./PipelineDesignBrowser";

export function PipelineLibrary({
  catalog, canEdit, onCreate, onOpen, onBack, backLabel = "Monitoring",
}: {
  catalog: PipelineCatalog;
  canEdit: boolean;
  onCreate: () => void;
  onOpen: (id: string) => void;
  onBack: () => void;
  backLabel?: string;
}) {
  return <section className="pl-library" aria-label="Templates">
    <Breadcrumb steps={[{ label: backLabel, onClick: onBack }]} current="Templates" />
    <div className="pl-header">
      <div>
        <h1>Templates</h1>
        <p className="pl-help">Reusable monitoring flows. Open a template to configure a service or update it.</p>
      </div>
      {canEdit && catalog.authoring_enabled && <button type="button" className="mn-primary" onClick={onCreate}>
        <Plus size={15} />Create monitoring service
      </button>}
    </div>
    {!catalog.authoring_enabled && <p className="pl-warning" role="status">
      Design authoring is disabled for this deployment. Existing designs and runs remain available to inspect.
    </p>}
    <PipelineDesignBrowser onSelect={onOpen} />
  </section>;
}
