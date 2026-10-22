import type { GraphDocument } from "./model";

export type EditorDraft = {
  document: GraphDocument;
  name: string;
  description: string;
};

export function isDraftDirty(current: EditorDraft, baseline: EditorDraft): boolean {
  return (
    JSON.stringify(current.document) !== JSON.stringify(baseline.document) ||
    current.name !== baseline.name ||
    current.description !== baseline.description
  );
}
