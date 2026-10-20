import { ArrowLeft, Plus } from "lucide-react";
import type { PipelineCatalog } from "./contracts";
import { PipelineDesignBrowser } from "./PipelineDesignBrowser";

export function PipelineLibrary({
  catalog, canEdit, onCreate, onOpen, onBack,
}: {
  catalog: PipelineCatalog;
  canEdit: boolean;
  onCreate: () => void;
  onOpen: (id: string) => void;
  onBack: () => void;
}) {
  return <section className="pl-library" aria-label="Templates">
    <button type="button" className="mn-back" onClick={onBack}>
      <ArrowLeft size={14} />Back
    </button>
    <div className="pl-header">
      <div>
        <h2>Templates</h2>
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
