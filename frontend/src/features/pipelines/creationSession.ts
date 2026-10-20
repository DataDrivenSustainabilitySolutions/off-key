import { useSyncExternalStore, type SetStateAction } from "react";
import { ApiRequestError } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/errors";
import { navigationDraft, navigationDraftGeneration, readStoredDraft, storeDraft } from "@/lib/navigation-draft";
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
  const generation = navigationDraftGeneration();
  const stored = (storageKey ? readStoredDraft(storageKey) : undefined) as Partial<CreationSnapshot> | undefined;
  const restored = storedDraft(stored?.draft) ?? storedDraft(stored);
  let snapshot: CreationSnapshot = {
    draft: restored ?? initial, baseline: storedDraft(stored?.baseline) ?? initial,
    template: stored?.template ?? template, save: { status: "idle" },
  };
  const listeners = new Set<() => void>();
  const update = (next: CreationSnapshot) => {
    if (generation !== navigationDraftGeneration()) return;
    snapshot = next;
    if (storageKey) storeDraft(storageKey, !next.template && !isSetupDirty(next.draft, next.baseline) ? undefined
      : { draft: next.draft, baseline: next.baseline, template: next.template });
    listeners.forEach((listener) => listener());
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    restored: !!restored,
    discard: (next: CreationDraft) => {
      if (snapshot.save.status === "saving") return;
      update({ draft: next, baseline: next, save: { status: "idle" } });
    },
    setDraft: (next: SetStateAction<CreationDraft>) => {
      const draft = typeof next === "function" ? next(snapshot.draft) : next;
      update({ ...snapshot, draft });
    },
    detachTemplate: () => update({ ...snapshot, template: undefined, save: { status: "idle" } }),
    save: async (details?: TemplateDetails) => {
      if (snapshot.save.status === "saving" || snapshot.save.status === "saved") return;
      const submitted = snapshot.draft;
      const metadata = details ?? { name: submitted.name.trim(), description: submitted.description };
      const base = details?.copy ? undefined : snapshot.template;
      update({ ...snapshot, save: { status: "saving" } });
      try {
        const body = { name: metadata.name.trim(), description: metadata.description,
          definition: submitted.document.definition, layout: submitted.document.layout };
        const saved = base
          ? await pipelinesApi.save(base.id, { ...body, expected_version: base.version })
          : await pipelinesApi.create(body);
        update({ ...snapshot, template: saved, baseline: submitted, save: { status: "saved" } });
        return true;
      } catch (reason) {
        update({ ...snapshot, save: { status: "error", message: getErrorMessage(reason),
          conflict: reason instanceof ApiRequestError && reason.status === 409 } });
        return false;
      }
    },
    acknowledge: () => { if (snapshot.save.status === "saved") update({ ...snapshot, save: { status: "idle" } }); },
    isDirty: () => isSetupDirty(snapshot.draft, snapshot.baseline),
  };
}

export function useCreationSession(key: string, initial: () => CreationDraft, template?: PipelineView) {
  const session = navigationDraft(key, () => createCreationSession(initial(), key, template));
  return { ...useSyncExternalStore(session.subscribe, session.getSnapshot), session };
}
