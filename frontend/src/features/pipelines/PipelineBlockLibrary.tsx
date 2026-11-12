import { useEffect, useId, useState } from "react";
import { Trash2 } from "lucide-react";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import type { PipelineBlock, PipelineComponent } from "./contracts";
import { pipelinesApi } from "./api";
import { blockSummary } from "./blocks";

/** The library's blocks, where one can be deleted. A step's menu in the editor saves them. */
export function PipelineBlockLibrary({ components, canEdit }: { components: PipelineComponent[]; canEdit: boolean }) {
  const heading = useId();
  const [blocks, setBlocks] = useState<PipelineBlock[]>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [deleting, setDeleting] = useState<string>();
  const [confirm, confirmation] = useConfirm();
  useEffect(() => {
    const controller = new AbortController();
    void pipelinesApi.blocks(controller.signal).then(
      (loaded) => { if (!controller.signal.aborted) { setBlocks(loaded); setError(""); } },
      (reason) => { if (!controller.signal.aborted) setError(getErrorMessage(reason)); },
    );
    return () => controller.abort();
  }, [retry]);
  const remove = async (block: PipelineBlock) => {
    if (!await confirm({ title: `Delete ${block.name}?`,
      description: "Services and templates that already hold its steps keep them.",
      confirmLabel: "Delete block", destructive: true })) return;
    setDeleting(block.id);
    setError("");
    try {
      await pipelinesApi.deleteBlock(block.id);
      setBlocks((previous) => previous?.filter((item) => item.id !== block.id));
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setDeleting(undefined);
    }
  };
  return <section className="pl-block-library" aria-labelledby={heading}>
    <h2 id={heading}>Blocks</h2>
    <p className="pl-help">Steps saved with their settings, to add to any service from the step menus.
      Save one from a step&apos;s menu in the editor.</p>
    {error && <p role="alert" className="pl-error">{error}
      {!blocks && <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry blocks</button>}
    </p>}
    {!blocks ? !error && <p role="status">Loading blocks…</p> : !blocks.length ? <p className="pl-help">No blocks saved yet.</p>
      : <ul className="pl-block-list">
        {blocks.map((block) => <li key={block.id}>
          <div>
            <strong>{block.name}</strong>
            <span>{block.description || blockSummary(block.steps, components)}</span>
          </div>
          <small>{block.steps.length === 1 ? "1 step" : `${block.steps.length} steps`}</small>
          {canEdit && <button type="button" aria-label={`Delete ${block.name}`} disabled={deleting === block.id}
            onClick={() => void remove(block)}><Trash2 size={15} aria-hidden="true" />Delete</button>}
        </li>)}
      </ul>}
    {confirmation}
  </section>;
}
