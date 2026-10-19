import { useSyncExternalStore, type SetStateAction } from "react";
import { getErrorMessage } from "@/lib/errors";
import { navigationDraft, readStoredDraft, storeDraft } from "@/lib/navigation-draft";
import { pipelinesApi } from "./api";
import type { PipelineView } from "./contracts";
import { acknowledgeSave, isDraftDirty, type EditorDraft } from "./editorSession";

export type CreationDraft = EditorDraft & {
  targetId?: string;
  startingId?: string;
};

type CreationSave =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; submitted: EditorDraft; pipeline: PipelineView }
  | { status: "error"; message: string };

type CreationSnapshot = {
  draft: CreationDraft;
  baseline: EditorDraft;
  save: CreationSave;
};

function storedDraft(value: unknown): CreationDraft | undefined {
  if (!value || typeof value !== "object") return;
  const draft = value as Partial<CreationDraft>;
  const definition = draft.document?.definition;
  if (typeof draft.name !== "string" || typeof draft.description !== "string"
    || !Array.isArray(definition?.nodes) || !Array.isArray(definition?.edges)
    || !Array.isArray(definition?.input_slots) || typeof draft.document?.layout?.nodes !== "object")
    return;
  return draft as CreationDraft;
}

/** The first save outlives the screen, just like the draft it acknowledges. */
export function createCreationSession(initial: CreationDraft, storageKey?: string) {
  const restored = storageKey ? storedDraft(readStoredDraft(storageKey)) : undefined;
  let snapshot: CreationSnapshot = {
    draft: restored ?? initial,
    baseline: initial,
    save: { status: "idle" },
  };
  const listeners = new Set<() => void>();
  const update = (next: CreationSnapshot) => {
    snapshot = next;
    if (storageKey)
      storeDraft(storageKey, next.save.status === "saved" || !isDraftDirty(next.draft, next.baseline)
        ? undefined : next.draft);
    listeners.forEach((listener) => listener());
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    /** True when the draft came back from a reload rather than this visit. */
    restored: !!restored,
    /** Drop every unsaved change and start again from the given draft. */
    discard: (next: CreationDraft) => {
      if (snapshot.save.status === "saving") return;
      update({ draft: next, baseline: next, save: { status: "idle" } });
    },
    setDraft: (next: SetStateAction<CreationDraft>) => {
      const draft = typeof next === "function" ? next(snapshot.draft) : next;
      update({ ...snapshot, draft });
    },
    save: async () => {
      if (snapshot.save.status === "saving" || snapshot.save.status === "saved") return;
      const submitted = snapshot.draft;
      update({ ...snapshot, save: { status: "saving" } });
      try {
        const pipeline = await pipelinesApi.create({
          name: submitted.name.trim(),
          description: submitted.description,
          definition: submitted.document.definition,
          layout: submitted.document.layout,
        });
        update({ ...snapshot, save: { status: "saved", submitted, pipeline } });
      } catch (reason) {
        update({ ...snapshot, save: { status: "error", message: getErrorMessage(reason) } });
      }
    },
    /** Only a mounted creation screen consumes the result and opens its editor. */
    takeSaved: (next: CreationDraft) => {
      if (snapshot.save.status !== "saved") return;
      const { draft, save } = snapshot;
      const { document, name, description } = draft;
      const result = {
        session: acknowledgeSave({ document, name, description }, save.submitted, save.pipeline),
        targetId: draft.targetId,
      };
      update({ draft: next, baseline: next, save: { status: "idle" } });
      return result;
    },
  };
}

export function useCreationSession(key: string, initial: () => CreationDraft) {
  const session = navigationDraft(key, () => createCreationSession(initial(), key));
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  return { ...snapshot, session };
}
