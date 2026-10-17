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
  return <section className="pl-library" aria-label="Saved designs">
    <button type="button" className="mn-back" onClick={onBack}>
      <ArrowLeft size={14} />Back
    </button>
    <div className="pl-header">
      <div>
        <h2>Saved designs</h2>
        <p className="pl-help">Manage reusable monitoring flows. Existing services keep their current revision.</p>
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
