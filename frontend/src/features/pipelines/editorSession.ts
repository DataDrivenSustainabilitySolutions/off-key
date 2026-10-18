import type { PipelineView } from "./contracts";
import type { GraphDocument } from "./model";

export type EditorDraft = {
  document: GraphDocument;
  name: string;
  description: string;
  activationRevisionId?: string;
};

export type EditorSession = EditorDraft & { base: PipelineView };

export function openSession(base: PipelineView): EditorSession {
  return {
    base,
    document: { definition: base.draft, layout: base.layout },
    name: base.name,
    description: base.description,
  };
}

/** A response acknowledges its submitted snapshot, never subsequent edits. */
export function acknowledgeSave(
  current: EditorDraft,
  submitted: EditorDraft,
  saved: PipelineView,
): EditorSession {
  return {
    ...current,
    base: saved,
    document:
      current.document === submitted.document
        ? { definition: saved.draft, layout: saved.layout }
        : current.document,
    name: current.name === submitted.name ? saved.name : current.name,
    description:
      current.description === submitted.description
        ? saved.description
        : current.description,
  };
}

export function isDraftDirty(current: EditorDraft, baseline: EditorDraft): boolean {
  return (
    JSON.stringify(current.document) !== JSON.stringify(baseline.document) ||
    current.name !== baseline.name ||
    current.description !== baseline.description
  );
}

export function isSessionDirty(session: EditorSession): boolean {
  return isDraftDirty(session, openSession(session.base));
}
