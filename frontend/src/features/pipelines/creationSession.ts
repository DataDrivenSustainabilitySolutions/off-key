import { useSyncExternalStore, type SetStateAction } from "react";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { createDraftStore, navigationDraft } from "@/lib/navigation-draft";
import { pipelinesApi } from "./api";
import type { PipelineView } from "./contracts";
import { isDraftDirty, type EditorDraft } from "./editorSession";

export type CreationDraft = EditorDraft & {
  targetId?: string;
  startingId?: string;
  bindings?: Record<string, string>;
};
type TemplateDetails = { name: string; description: string; copy?: boolean };
type CreationSave = { status: "idle" | "saving" | "saved"; message?: never; conflict?: never }
  | { status: "error"; message: string; conflict: boolean };
type CreationSnapshot = {
  draft: CreationDraft;
  baseline: CreationDraft;
  template?: PipelineView;
  save: CreationSave;
};

const isSetupDirty = (draft: CreationDraft, baseline: CreationDraft) => isDraftDirty(draft, baseline)
  || draft.targetId !== baseline.targetId || JSON.stringify(draft.bindings ?? {}) !== JSON.stringify(baseline.bindings ?? {});

function storedDraft(value: unknown): CreationDraft | undefined {
  if (!value || typeof value !== "object") return;
  const draft = value as Partial<CreationDraft>;
  if (typeof draft.name !== "string" || typeof draft.description !== "string"
    || !Array.isArray(draft.document?.definition?.nodes) || !Array.isArray(draft.document?.definition?.edges)
    || !Array.isArray(draft.document?.definition?.input_slots) || typeof draft.document?.layout?.nodes !== "object") return;
  return draft as CreationDraft;
}

/** Template saves survive navigation without moving the user to another workflow. */
export function createCreationSession(initial: CreationDraft, storageKey?: string, template?: PipelineView) {
  let restored: CreationDraft | undefined;
  const store = createDraftStore<CreationSnapshot>(storageKey, (value) => {
    const stored = value as Partial<CreationSnapshot> | undefined;
    restored = storedDraft(stored?.draft) ?? storedDraft(stored);
    return { draft: restored ?? initial, baseline: storedDraft(stored?.baseline) ?? initial,
      template: stored?.template ?? template, save: { status: "idle" } };
  }, (next) => !next.template && !isSetupDirty(next.draft, next.baseline) ? undefined
    : { draft: next.draft, baseline: next.baseline, template: next.template });
  const { update, getSnapshot } = store;
  return {
    getSnapshot,
    subscribe: store.subscribe,
    restored: !!restored,
    discard: (next: CreationDraft) => {
      if (getSnapshot().save.status === "saving") return;
      update({ draft: next, baseline: next, save: { status: "idle" } });
    },
    setDraft: (next: SetStateAction<CreationDraft>) => {
      const draft = typeof next === "function" ? next(getSnapshot().draft) : next;
      update({ ...getSnapshot(), draft });
    },
    detachTemplate: () => update({ ...getSnapshot(), template: undefined, save: { status: "idle" } }),
    save: async (details?: TemplateDetails) => {
      if (getSnapshot().save.status === "saving" || getSnapshot().save.status === "saved") return;
      const submitted = getSnapshot().draft;
      const metadata = details ?? { name: submitted.name.trim(), description: submitted.description };
      const base = details?.copy ? undefined : getSnapshot().template;
      update({ ...getSnapshot(), save: { status: "saving" } });
      try {
        const body = { name: metadata.name.trim(), description: metadata.description,
          definition: submitted.document.definition, layout: submitted.document.layout };
        const saved = base
          ? await pipelinesApi.save(base.id, { ...body, expected_version: base.version })
          : await pipelinesApi.create(body);
        update({ ...getSnapshot(), template: saved, baseline: submitted, save: { status: "saved" } });
        return true;
      } catch (reason) {
        update({ ...getSnapshot(), save: { status: "error", message: getErrorMessage(reason),
          conflict: reason instanceof ApiRequestError && reason.status === 409 } });
        return false;
      }
    },
    acknowledge: () => { if (getSnapshot().save.status === "saved") update({ ...getSnapshot(), save: { status: "idle" } }); },
    isDirty: () => isSetupDirty(getSnapshot().draft, getSnapshot().baseline),
  };
}

export function useCreationSession(key: string, initial: () => CreationDraft, template?: PipelineView) {
  const session = navigationDraft(key, () => createCreationSession(initial(), key, template));
  return { ...useSyncExternalStore(session.subscribe, session.getSnapshot), session };
}
